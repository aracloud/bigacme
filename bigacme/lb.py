"""Functions that interacts with the loadbalancer"""
import logging
import bigsuds

logger = logging.getLogger(__name__)

# suds is very noisy
logging.getLogger("suds.client").setLevel(logging.CRITICAL)


class LoadBalancerError(Exception):
    """Superclass for all load balancer exceptions."""

    pass


class CouldNotConnectToBalancerError(LoadBalancerError):
    """Raised when a connection to the (active) load balancer could not be made"""

    pass


class PartitionNotFoundError(LoadBalancerError):
    """Raised when the partition was not found"""

    pass


class CSRNotFoundError(LoadBalancerError):
    """Raised when the CSR was not found on the device"""

    pass


class AccessDeniedError(LoadBalancerError):
    """Raised when the device denies access"""

    pass


class NotFoundError(LoadBalancerError):
    """Raised when the specified resource was not found on the load balancer"""

    pass


class LoadBalancer:
    """Represent the LoadBalancer"""

    def __init__(self, config):
        """Connects to the Big-IP unit(s)"""
        self.partition, self.datagroup = config.lb_dg_partition, config.lb_dg

        lb1 = bigsuds.BIGIP(config.lb1, config.lb_user, config.lb_pwd, verify=True)
        if config.lb2:
            lb2 = bigsuds.BIGIP(config.lb2, config.lb_user, config.lb_pwd, verify=True)

            try:
                if lb1.System.Failover.get_failover_state() == "FAILOVER_STATE_ACTIVE":
                    self.bigip = lb1
                    return
            except bigsuds.OperationFailed:
                logger.exception("Could not get failover status from %s", config.lb1)

            try:
                if lb2.System.Failover.get_failover_state() == "FAILOVER_STATE_ACTIVE":
                    self.bigip = lb2
                    return
            except bigsuds.OperationFailed:
                logger.exception("Could not get failover status from %s", config.lb2)

            raise CouldNotConnectToBalancerError(
                "None of the available devices were active. "
                "See the log for more details."
            )

        else:
            # Just to check the connection
            try:
                lb1.System.SystemInfo.get_uptime()
            except bigsuds.OperationFailed as error:
                raise CouldNotConnectToBalancerError(error)
            self.bigip = lb1

    def send_challenge(self, domain: str, path: str, string: str) -> None:
        """Sends the challenge to the Big-IP"""
        shortpath = path.split("/")[-1]
        key = f"{domain}:{shortpath}"
        logger.debug(
            "Adding record %s with value %s to datagroup %s in partition %s",
            key,
            string,
            self.datagroup,
            self.partition,
        )
        self.bigip.System.Session.set_active_folder(f"/{self.partition}")
        datagroup = self.bigip.LocalLB.Class
        class_members = [{"name": self.datagroup, "members": [key]}]
        try:
            datagroup.add_string_class_member(class_members)
        except bigsuds.ServerError as error:
            if (
                f"The requested class string item (/{self.partition}/{self.datagroup}"
                f" {key}) already exists in partition"
            ) in error.fault.faultstring:
                logger.debug(
                    "The record already exist. Deleting it before adding it again"
                )
                self.remove_challenge(domain, path)
                datagroup.add_string_class_member(class_members)
            else:
                raise
        datagroup.set_string_class_member_data_value(class_members, [[string]])

    def remove_challenge(self, domain: str, path: str) -> None:
        """Removes the challenge from the Big-IP"""
        shortpath = path.split("/")[-1]
        key = f"{domain}:{shortpath}"
        logger.debug(
            "Removing record %s from datagroup %s in partition %s",
            key,
            self.datagroup,
            self.partition,
        )
        self.bigip.System.Session.set_active_folder(f"/{self.partition}")
        datagroup = self.bigip.LocalLB.Class
        class_members = [{"name": self.datagroup, "members": [key]}]
        datagroup.delete_string_class_member(class_members)

    def get_csr(self, partition: str, csrname: str) -> str:
        """Downloads the specified csr"""
        try:
            self.bigip.System.Session.set_active_folder(f"/{partition}")
        except bigsuds.ServerError as error:
            if "folder not found" in error.fault.faultstring:
                raise PartitionNotFoundError()
            elif "Access Denied:" in error.fault.faultstring:
                raise AccessDeniedError()
            else:
                raise
        try:
            pem_csr = self.bigip.Management.KeyCertificate.certificate_request_export_to_pem(
                "MANAGEMENT_MODE_DEFAULT", [csrname]
            )[
                0
            ]
        except bigsuds.ServerError as error:
            if "Access Denied:" in error.fault.faultstring:
                raise AccessDeniedError()
            elif "Not Found" in error.fault.faultstring:
                raise NotFoundError()
            else:
                raise
        return pem_csr

    def upload_certificate(self, partition: str, name: str, certificates: str) -> None:
        """Uploads a new certificate to the Big-IP"""
        try:
            self.bigip.System.Session.set_active_folder(f"/{partition}")
        except bigsuds.ServerError as error:
            if "folder not found" in error.fault.faultstring:
                raise PartitionNotFoundError()
            elif "Access Denied:" in error.fault.faultstring:
                raise AccessDeniedError()
            else:
                raise
        try:
            self.bigip.Management.KeyCertificate.certificate_import_from_pem(
                "MANAGEMENT_MODE_DEFAULT", [name], [certificates], True
            )
        except bigsuds.ServerError as error:
            if "Access Denied:" in error.fault.faultstring:
                raise AccessDeniedError()
            else:
                raise
