"""Functions that interacts with the CA"""
import os
import logging
from collections import namedtuple

from acme import client
from acme import messages
from acme import jose
from acme import errors as acme_errors
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import serialization

import OpenSSL

logger = logging.getLogger(__name__)


class CAError(Exception):
    """Superclass for all ca exceptions."""
    pass
class NoHTTPChallenge(CAError):
    """Raised when there is no http challenge to be solved"""
    pass
class GetCertificateFailedError(CAError):
    """Raised when it was not possible to get the certificate"""
    pass

class CertificateAuthority(object):
    """Represent a Certificate Authority"""

    def __init__(self, configuration, test=False):
        if test:
            self.key = None
        else:
            with open(configuration.cm_key, "r") as key_file:
                private_key = serialization.load_pem_private_key(
                    key_file.read(),
                    password=None,
                    backend=default_backend()
                    )
            self.key = jose.JWKRSA(key=private_key)
        self.proxy = configuration.ca_proxy
        self.set_proxy()
        user_agent = 'bigacme (https://github.com/magnuswatn/bigacme/)'
        network = client.ClientNetwork(self.key, user_agent=user_agent)
        acme_client = client.Client(directory=configuration.ca, key=self.key, net=network)
        self.unset_proxy()
        self.client = acme_client

    def set_proxy(self):
        """Sets the proxy server to the specified server (if any)"""
        if self.proxy:
            os.environ["https_proxy"] = self.proxy

    def unset_proxy(self):
        """Removes the set proxy"""
        if self.proxy:
            os.environ["https_proxy"] = ""

    def register(self, mail):
        """Registers an account with the ca"""
        self.set_proxy()
        registration = messages.NewRegistration.from_data(email=mail)
        regr = self.client.register(registration)
        logger.info("Auto-accepting TOS: %s", regr.terms_of_service)
        self.client.agree_to_tos(regr)
        logger.info("Registered with the CA")
        self.unset_proxy()

    def get_http_challenge_for_domains(self, hostnames):
        """Gets challenges from the CA, and return the HTTP ones"""
        challenges = self.get_challenge_for_domains(hostnames)
        http_challenges = _return_http_challenges(challenges)
        return self.return_tuple_from_challenges(http_challenges), challenges

    def get_challenge_for_domains(self, hostnames):
        """Asks the CA for challenges for the specified domains"""
        self.set_proxy()
        challenges = []
        for hostname in hostnames:
            challenges += [self.client.request_domain_challenges(hostname)]
        self.unset_proxy()
        return challenges

    def answer_challenges(self, challenges):
        """Tells the CA that the challenges has been solved"""
        self.set_proxy()
        for challenge in challenges:
            logger.debug("Answering challenge for the domain: %s", challenge.domain)
            self.client.answer_challenge(challenge.challenge, challenge.response)
        self.unset_proxy()

    def revoke_certifciate(self, cert_pem, reason):
        """Revokes a certificate"""
        self.set_proxy()
        cert = OpenSSL.crypto.load_certificate(OpenSSL.crypto.FILETYPE_PEM, cert_pem)
        jose_cert = jose.util.ComparableX509(cert)
        self.client.revoke(jose_cert, reason)
        self.unset_proxy()

    def get_certificate_from_ca(self, csr_pem, authorizations):
        """Sends the CSR to the CA and gets a signed certificate in return"""
        self.set_proxy()
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

        cert = certificateresource.body._dump(OpenSSL.crypto.FILETYPE_PEM) # pylint: disable=protected-access
        chain_certs = self.client.fetch_chain(certificateresource)
        chain = []
        for chaincert in chain_certs:
            chain.append(chaincert._dump(OpenSSL.crypto.FILETYPE_PEM)) # pylint: disable=protected-access
        self.unset_proxy()
        return cert, chain

    def return_tuple_from_challenges(self, http_challenges):
        """Returns a challenge tuple from a list of challenges"""
        challtp = namedtuple("Authz", ["domain", "path", "validation", "response", "challenge"])
        tuples = []
        for challenge in http_challenges:
            response, validation = challenge[1].response_and_validation(self.key)
            tuples += [challtp(domain=challenge[0], path=challenge[1].path,
                               validation=validation, response=response, challenge=challenge[1])]
        return tuples

def _return_http_challenges(challenges):
    """Returns the http challenge"""
    http_challenges = []
    for challenge in challenges:
        http_challenge = False
        logger.debug("This challenge is for the domain: %s", challenge.body.identifier.value)
        for subchallenge in challenge.body.challenges:
            logger.debug("This challenge is of type %s", subchallenge.chall.typ)
            if subchallenge.chall.typ == "http-01":
                logger.debug("This challenge is of http :-)")
                http_challenges += [[challenge.body.identifier.value, subchallenge]]
                http_challenge = True
        if not http_challenge:
            logger.debug("Found no http challenge for this domain, raising NoHTTPChallenge")
            raise NoHTTPChallenge
    return http_challenges
