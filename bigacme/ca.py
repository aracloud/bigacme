"""Functions that interacts with the CA"""
import logging
from collections import namedtuple

import josepy as jose
from acme import client
from acme import messages
from acme import errors as acme_errors
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import serialization

import OpenSSL

logger = logging.getLogger(__name__)


class CAError(Exception):
    """Superclass for all ca exceptions."""
    pass
class NoDesiredChallenge(CAError):
    """Raised when the CA did not provides the desired challenge for the domain"""
    pass
class GetCertificateFailedError(CAError):
    """Raised when it was not possible to get the certificate"""
    pass
class UnknownValidationType(CAError):
    """Raised when the validation type is not recognized"""
    pass

class CertificateAuthority:
    """Represent a Certificate Authority"""

    def __init__(self, configuration, test=False):
        if test:
            self.key = None
        else:
            with open(configuration.cm_key, "rb") as key_file:
                private_key = serialization.load_pem_private_key(
                    key_file.read(),
                    password=None,
                    backend=default_backend()
                    )
            self.key = jose.JWKRSA(key=private_key)
        user_agent = 'bigacme (https://github.com/magnuswatn/bigacme/)'
        network = client.ClientNetwork(self.key, user_agent=user_agent)
        network.session.proxies = {'https': configuration.ca_proxy}
        acme_client = client.Client(directory=configuration.ca, key=self.key, net=network)
        self.client = acme_client

    def register(self, mail):
        """Registers an account with the ca"""
        registration = messages.NewRegistration.from_data(email=mail)
        regr = self.client.register(registration)
        logger.info("Auto-accepting TOS: %s", regr.terms_of_service)
        self.client.agree_to_tos(regr)
        logger.info("Registered with the CA")

    def get_challenge_for_domains(self, hostnames, typ):
        """Asks the CA for challenges for the specified domains"""
        authz = []
        for hostname in hostnames:
            authz += [self.client.request_domain_challenges(hostname)]
        desired_challenges = _return_desired_challenges(authz, typ)
        return self.return_tuple_from_challenges(desired_challenges), authz

    def answer_challenges(self, challenges):
        """Tells the CA that the challenges has been solved"""
        for challenge in challenges:
            logger.debug("Answering challenge for the domain: %s", challenge.domain)
            self.client.answer_challenge(challenge.challenge, challenge.response)

    def revoke_certifciate(self, cert_pem, reason):
        """Revokes a certificate"""
        cert = OpenSSL.crypto.load_certificate(OpenSSL.crypto.FILETYPE_PEM, cert_pem)
        jose_cert = jose.util.ComparableX509(cert)
        self.client.revoke(jose_cert, reason)

    def get_certificate_from_ca(self, csr_pem, authorizations):
        """Sends the CSR to the CA and gets a signed certificate in return"""
        csr = OpenSSL.crypto.load_certificate_request(OpenSSL.crypto.FILETYPE_PEM, csr_pem)
        jose_csr = jose.util.ComparableX509(csr)
        logger.debug("Getting the certificate from the CA")
        try:
            certificateresource, _ = self.client.poll_and_request_issuance(jose_csr, authorizations)
        except acme_errors.PollError as error:
            if error.timeout:
                raise GetCertificateFailedError(
                    "Timed out while waiting for the CA to verify the challenges")
            else:
                raise GetCertificateFailedError("The CA could not verify the challenges")

        cert = certificateresource.body._dump(OpenSSL.crypto.FILETYPE_PEM).decode() # pylint: disable=protected-access
        chain_certs = self.client.fetch_chain(certificateresource)
        chain = []
        for chaincert in chain_certs:
            chain.append(chaincert._dump(OpenSSL.crypto.FILETYPE_PEM).decode()) # pylint: disable=protected-access
        return cert, chain

    def return_tuple_from_challenges(self, challenges):
        """Returns a challenge tuple from a list of challenges"""
        challtp = namedtuple("Authz", ["domain", "validation", "response", "challenge"])
        tuples = []
        for challenge in challenges:
            response, validation = challenge[1].response_and_validation(self.key)
            tuples += [challtp(domain=challenge[0], validation=validation, response=response,
                               challenge=challenge[1])]
        return tuples

def _return_desired_challenges(challenges, typ):
    desired_challenges = []
    for challenge in challenges:
        desired_challenge = [ch for ch in challenge.body.challenges if ch.typ == typ]
        if desired_challenge:
            desired_challenges += [[challenge.body.identifier.value, desired_challenge[0]]]
        else:
            raise NoDesiredChallenge('The CA didn\'t provide a %s challenge' % typ)
    return desired_challenges
