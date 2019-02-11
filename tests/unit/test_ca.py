"""Tests for ca.py"""
import pytest
from bigacme import ca
from acme import messages
from acme import challenges
from acme import errors as acme_errors

from unittest.mock import MagicMock


def test_return_desired_challenges():
    """_return_desired_challenges should return the challenges of the spesified type"""
    identifier = messages.Identifier(
        typ=messages.IdentifierType("dns"), value="dummydomene"
    )
    dns_chall = messages.ChallengeBody(chall=challenges.DNS01(), status="pending")
    http_chal = messages.ChallengeBody(chall=challenges.HTTP01(), status="pending")
    authz = messages.Authorization(
        challenges=(dns_chall, http_chal), identifier=identifier
    )
    authzr = [messages.AuthorizationResource(body=authz)]
    desired_chall = ca._return_desired_challenges(authzr, "http-01")
    assert desired_chall[0][0] == "dummydomene"
    assert desired_chall[0][1] == http_chal


def test_return_desired_challenges_several_domains():
    """
    _return_desired_challenges should return the challenges of the spesified type
    for all the domains
    """
    identifier1 = messages.Identifier(
        typ=messages.IdentifierType("dns"), value="domene1.no"
    )
    dns_chall1 = messages.ChallengeBody(chall=challenges.DNS01(), status="pending")
    http_chall1 = messages.ChallengeBody(chall=challenges.HTTP01(), status="pending")
    authz1 = messages.Authorization(
        challenges=(dns_chall1, http_chall1), identifier=identifier1
    )

    identifier2 = messages.Identifier(
        typ=messages.IdentifierType("dns"), value="domene2.no"
    )
    dns_chall2 = messages.ChallengeBody(chall=challenges.DNS01(), status="pending")
    http_chall2 = messages.ChallengeBody(chall=challenges.HTTP01(), status="pending")
    authz2 = messages.Authorization(
        challenges=(dns_chall2, http_chall2), identifier=identifier2
    )

    authzr = [
        messages.AuthorizationResource(body=authz1),
        messages.AuthorizationResource(body=authz2),
    ]

    desired_chall = ca._return_desired_challenges(authzr, "dns-01")
    assert desired_chall[0][0] == "domene1.no"
    assert desired_chall[0][1] == dns_chall1
    assert desired_chall[1][0] == "domene2.no"
    assert desired_chall[1][1] == dns_chall2


def test_return_desired_challenges_missing_for_one():
    """
    If the specified challenge type is missing for one of the domains,
    _return_desired_challenges should throw an exception
    """
    identifier1 = messages.Identifier(
        typ=messages.IdentifierType("dns"), value="domene1.no"
    )
    http_chall1 = messages.ChallengeBody(chall=challenges.HTTP01(), status="pending")
    weird_chall1 = messages.ChallengeBody(
        chall=challenges.UnrecognizedChallenge, status="pending"
    )
    authz1 = messages.Authorization(
        challenges=(http_chall1, weird_chall1), identifier=identifier1
    )

    identifier2 = messages.Identifier(
        typ=messages.IdentifierType("dns"), value="domene2.no"
    )
    dns_chall2 = messages.ChallengeBody(chall=challenges.DNS01(), status="pending")
    http_chall2 = messages.ChallengeBody(chall=challenges.HTTP01(), status="pending")
    authz2 = messages.Authorization(
        challenges=(dns_chall2, http_chall2), identifier=identifier2
    )

    authzr = [
        messages.AuthorizationResource(body=authz1),
        messages.AuthorizationResource(body=authz2),
    ]

    with pytest.raises(ca.NoDesiredChallenge):
        ca._return_desired_challenges(authzr, "dns-01")


def test_validate_cert_chain_vaild_chain():
    """With a normal chain with certs, nothing should happen"""
    pem_chain = """
    -----BEGIN CERTIFICATE-----
    tralallalalal
    -----END CERTIFICATE-----
    -----BEGIN CERTIFICATE-----
    tralallalalal
    -----END CERTIFICATE-----"""
    ca._validate_cert_chain(pem_chain)


def test_validate_cert_chain_invaild_chain():
    """Should raise an exception if the cert chain contains fishy stuff"""
    pem_chain = """
    -----BEGIN CERTIFICATE-----
    tralallalalal
    -----END CERTIFICATE-----
    -----BEGIN PRIVATE KEY-----
    tralallalalal
    -----END PRIVATE KEY-----"""
    with pytest.raises(ca.ReceivedInvalidCertificateError):
        ca._validate_cert_chain(pem_chain)


def test_get_certificate_from_ca_timeout():
    fake_ca = MagicMock(spec=ca.CertificateAuthority)
    order = MagicMock()
    fake_ca.client = MagicMock()
    fake_ca.client.poll_and_finalize.side_effect = acme_errors.TimeoutError
    with pytest.raises(ca.GetCertificateFailedError) as error:
        ca.CertificateAuthority.get_certificate_from_ca(fake_ca, order)
    assert (
        str(error.value)
        == "Timed out while waiting for the CA to verify the challenges"
    )


def test_get_certificate_from_ca_error_from_server():
    fake_ca = MagicMock(spec=ca.CertificateAuthority)
    order = MagicMock()
    fake_ca.client = MagicMock()
    fake_ca.client.poll_and_finalize.side_effect = messages.Error
    with pytest.raises(ca.GetCertificateFailedError) as error:
        ca.CertificateAuthority.get_certificate_from_ca(fake_ca, order)


def test_get_certificate_from_ca_weird_error():
    fake_ca = MagicMock(spec=ca.CertificateAuthority)
    order = MagicMock()
    fake_ca.client = MagicMock()
    fake_ca.client.poll_and_finalize.side_effect = acme_errors.UnexpectedUpdate("what")
    with pytest.raises(ca.GetCertificateFailedError) as error:
        ca.CertificateAuthority.get_certificate_from_ca(fake_ca, order)
    assert str(error.value) == "what"
