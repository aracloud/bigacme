import os
import pwd
import json
import shutil
import tempfile
from collections import namedtuple
from datetime import datetime, timedelta

import pytest
import OpenSSL

import bigacme.cert

ORG_CWD = os.getcwd()

FOLDERS = ["config", "cert", "cert/backup"]

def setup_module(module):
    temp_dir = tempfile.mkdtemp()
    os.chdir(temp_dir)
    for folder in FOLDERS:
        os.makedirs(folder)

def teardown_module(module):
    if '/tmp/' in os.getcwd():
        shutil.rmtree(os.getcwd())
    os.chdir(ORG_CWD)

def _generate_certificate(not_before, not_after):
    """Generates a certificate in a file for testing purposes"""
    key = OpenSSL.crypto.PKey()
    key.generate_key(OpenSSL.crypto.TYPE_RSA, 1024)
    cert = OpenSSL.crypto.X509()
    cert.set_serial_number(357)
    cert.get_subject().CN = "test"
    cert.set_issuer(cert.get_subject())
    cert.gmtime_adj_notBefore(not_before)
    cert.gmtime_adj_notAfter(not_after)
    cert.set_pubkey(key)
    cert.sign(key, "sha256")
    return OpenSSL.crypto.dump_certificate(OpenSSL.crypto.FILETYPE_PEM, cert)

def _generate_csr(cn, san):
    """Generates a csr for testing purposes"""
    key = OpenSSL.crypto.PKey()
    key.generate_key(OpenSSL.crypto.TYPE_RSA, 1024)
    req = OpenSSL.crypto.X509Req()
    if cn:
        req.get_subject().CN = cn
    if san:
        sn = ([OpenSSL.crypto.X509Extension("subjectAltName", False, san)])
        req.add_extensions(sn)
    req.set_pubkey(key)
    req.sign(key, "sha256")
    return OpenSSL.crypto.dump_certificate_request(
        OpenSSL.crypto.FILETYPE_PEM, req)

def test_get_certs_that_need_action():
    configtp = namedtuple('Config', ['cm_renewal_days', 'cm_delayed_days'])
    config = configtp(cm_renewal_days=12, cm_delayed_days=4)
    csr = _generate_csr('commonName', 'DNS:san1,DNS:san2')

    # certs to be renewed
    cert_tbr1 = bigacme.cert.Certificate.new('Common', 'cert_tbr1', csr, 'http-01')
    cert_tbr1.cert = _generate_certificate(-90800, 4320)
    cert_tbr1.mark_as_installed()
    cert_tbr2 = bigacme.cert.Certificate.new('Common', 'cert_tbr2', csr, 'http-01')
    cert_tbr2.cert = _generate_certificate(-9320000, 90800)
    cert_tbr2.mark_as_installed()

    # certs to be installed
    cert_tbi1 = bigacme.cert.Certificate.new('Common', 'cert_tbi1', csr, 'http-01')
    cert_tbi1.cert = _generate_certificate(-995700, 1923200)
    cert_tbi1.status = 'To be installed'
    cert_tbi1.save()

    cert_tbi2 = bigacme.cert.Certificate.new('Common', 'cert_tbi2', csr, 'http-01')
    cert_tbi2.cert = _generate_certificate(-999700, 9123200)
    cert_tbi2.status = 'To be installed'
    cert_tbi2.save()

    # cert that neither
    cert_tbnothin = bigacme.cert.Certificate.new('Common', 'cert_tbnothin', csr, 'http-01')
    cert_tbnothin.cert = _generate_certificate(-29123200, 29123200)
    cert_tbnothin.mark_as_installed()

    # random file in folder
    with open('./cert/not_json.json', 'w') as open_file:
        open_file.write('this is not json')
    tbr, tbi = bigacme.cert.get_certs_that_need_action(config)
    tbr_names = tbi_names = []
    for cert in tbr:
        tbr_names.append(cert.name)
    for cert in tbi:
        tbi_names.append(cert.name)
    assert 'cert_tbr1' and 'cert_tbr2' in tbr_names
    assert 'cert_tbi1' and 'cert_tbi2' and 'cert_tbnothin' not in tbr_names
    assert 'cert_tbi1' and 'cert_tbi2' in tbi_names
    assert 'cert_tbr1' and 'cert_tbr2' and 'cert_tbnothin' not in tbi_names

def test_cert_about_to_expire():
    """Tests if a certificate about to expires is detected"""
    cert = _generate_certificate(-10800, 432000)
    not_after_str, _ = bigacme.cert._get_cert_dates(cert)
    assert bigacme.cert._check_if_cert_about_to_expire(not_after_str, 14)

def test_cert_not_about_to_expire():
    """Tests if a certificate not about to expire is not detected"""
    cert = _generate_certificate(-10800, 15552000)
    not_after_str, _ = bigacme.cert._get_cert_dates(cert)
    assert not bigacme.cert._check_if_cert_about_to_expire(not_after_str, 14)

def test_get_cert_dates():
    cert = _generate_certificate(-10800, 15552000)
    actual_nva, actual_nvb = bigacme.cert._get_cert_dates(cert)
    expected_nva = (datetime.today().utcnow() +
                    timedelta(seconds=15552000)).strftime('%Y-%m-%dT%H:%M:%S')
    expected_nvb = (datetime.today().utcnow() +
                    timedelta(seconds=-10800)).strftime('%Y-%m-%dT%H:%M:%S')
    assert actual_nva == expected_nva
    assert actual_nvb == expected_nvb

def test_delete_expired_backups():
    cert = _generate_certificate(-10800, 15552000)
    expired_cert = _generate_certificate(-10800, -10)
    with open('./cert/backup/cert', 'w') as open_file:
        open_file.write(cert)
    with open('./cert/backup/expired_cert', 'w') as open_file:
        open_file.write(expired_cert)
    with open('./cert/backup/not_a_cert', 'w') as open_file:
        open_file.write('this is not a cert')
    bigacme.cert.delete_expired_backups()
    assert os.path.isfile('./cert/backup/cert')
    assert not os.path.isfile('./cert/backup/expired_cert')

def test__init__certificate():
    cert = bigacme.cert.Certificate('Partition', 'Name')
    assert cert.partition == 'Partition'
    assert cert.name == 'Name'
    assert cert.status == 'New'
    assert cert.path == './cert/%s_%s.json' % ('Partition', 'Name')
    assert cert.validation_method == 'http-01'

def test_new_certificate():
    csr = _generate_csr('common-name', 'DNS:san1,DNS:san2')
    cert = bigacme.cert.Certificate.new('Partition', 'test_new_certificate', csr, 'dns-01')
    assert cert.partition == 'Partition'
    assert cert.name == 'test_new_certificate'
    assert cert.csr == csr
    assert cert.validation_method == 'dns-01'
    assert 'common-name' and 'san1' and 'san2' in cert.hostnames

def test_new_certificate_no_cn():
    csr = _generate_csr(None, 'DNS:san')
    cert = bigacme.cert.Certificate.new('Partition', 'test_new_certificate_no_cn', csr, 'http-01')
    assert cert.csr == csr
    assert cert.hostnames == ['san']

def test_new_certificate_no_san():
    csr = _generate_csr('common-name', None)
    cert = bigacme.cert.Certificate.new('Partition', 'test_new_certificate_no_san', csr, 'http-01')
    assert cert.csr == csr
    assert cert.hostnames == ['common-name']

def test_new_certificate_commonName_in_san():
    """Same name both in CN and SAN should not result in duplicate name in hostnames"""
    csr = _generate_csr('common-name', 'DNS:san1,DNS:common-name,DNS:san2')
    cert = bigacme.cert.Certificate.new('Partition', 'test_new_certificate_no_san', csr, 'http-01')
    assert cert.csr == csr
    assert len(cert.hostnames) == len(set(cert.hostnames))

def test_get_non_existing_cert():
    with pytest.raises(bigacme.cert.CertificateNotFoundError):
        bigacme.cert.Certificate.get('Common', 'test_get_non_existing_cert')

def test_save_and_get():
    csr = _generate_csr('common-name', 'DNS:san1,DNS:san2')
    cert = bigacme.cert.Certificate.new('Partition', 'test_save_and_get', csr, 'http-01')
    cert.save()
    cert2 = bigacme.cert.Certificate.get('Partition', 'test_save_and_get')
    assert cert.__dict__ == cert2.__dict__

def test_get_without_validation_method():
    """Tests that a json withouth validation method fallbacks to http-01"""
    csr = _generate_csr('common-name', 'DNS:san1,DNS:san2')
    cert = bigacme.cert.Certificate.new('Partition', 'test_get_without_validation_method', csr,
                                        'dns-01')
    cert.save()
    with open(cert.path, 'r+') as json_bytes:
        json_dict = json.loads(json_bytes.read())
        json_dict.pop('validation_method')
        json_bytes.seek(0)
        json_bytes.write(json.dumps(json_dict))
        json_bytes.truncate()
    cert2 = bigacme.cert.Certificate.get('Partition', 'test_get_without_validation_method')
    assert cert2.validation_method == 'http-01'

def test_save_and_delete():
    csr = _generate_csr('common-name', 'DNS:san1,DNS:san2')
    cert = bigacme.cert.Certificate.new('Common', 'test_save_and_delete', csr, 'http-01')
    cert.save()
    assert os.path.isfile(cert.path)
    cert.delete()
    assert not os.path.isfile(cert.path)

def test_get_pem():
    csr = _generate_csr('common-name', 'DNS:san1,DNS:san2')
    cert = bigacme.cert.Certificate.new('Common', 'test_get_pem', csr, 'http-01')
    cert.cert = _generate_certificate(0, 1555200)
    cert.chain = [_generate_certificate(0, 1555200)]
    assert cert.get_pem(False) == cert.cert

def test_get_pem_with_chain():
    csr = _generate_csr('common-name', 'DNS:san1,DNS:san2')
    cert = bigacme.cert.Certificate.new('Common', 'test_get_pem', csr, 'http-01')
    cert.cert = _generate_certificate(0, 1555200)
    cert.chain = [_generate_certificate(0, 1555200)]
    cert_and_chain = cert.cert + cert.chain[0]
    assert cert.cert and cert.chain[0] in cert.get_pem(True)
    assert cert.get_pem(True) == cert_and_chain

def test_mark_as_installed():
    csr = _generate_csr('common-name', 'DNS:san1,DNS:san2')
    cert = bigacme.cert.Certificate.new('Common', 'test_mark_as_installed', csr, 'http-01')
    cert.save()
    assert cert.status == 'New'
    with open(cert.path, 'r') as json_bytes:
        assert json.loads(json_bytes.read())['status'] == 'New'
    cert.mark_as_installed()
    assert cert.status == 'Installed'
    with open(cert.path, 'r') as json_bytes:
        assert json.loads(json_bytes.read())['status'] == 'Installed'

def test_renew():
    csr = _generate_csr('common-name', 'DNS:san1,DNS:san2')
    cert = bigacme.cert.Certificate.new('Common', 'test_renew', csr, 'http-01')
    org_cert = _generate_certificate(0, 1555200)
    org_chain = _generate_certificate(0, 1555200)
    cert.cert, cert.chain = org_cert, org_chain
    new_cert = _generate_certificate(0, 1555200)
    new_chain = _generate_certificate(0, 1555200)
    cert.renew(new_cert, [new_chain])
    assert os.path.isfile('./cert/backup/Common_test_renew.cer')
    assert cert.status == 'To be installed'

def test_old_enough():
    csr = _generate_csr('common-name', 'DNS:san1,DNS:san2')
    cert = bigacme.cert.Certificate.new('Common', 'test_old_enough', csr, 'http-01')
    cert.cert = _generate_certificate(-1980000, 4320000)
    assert cert.old_enough(13)

def test_not_old_enough():
    csr = _generate_csr('common-name', 'DNS:san1,DNS:san2')
    cert = bigacme.cert.Certificate.new('Common', 'test_old_enough', csr, 'http-01')
    cert.cert = _generate_certificate(0, 4320000)
    assert not cert.old_enough(14)

def test_about_to_expire():
    csr = _generate_csr('common-name', 'DNS:san1,DNS:san2')
    cert = bigacme.cert.Certificate.new('Common', 'test_about_to_expire', csr, 'http-01')
    cert.cert = _generate_certificate(-10800, 432000)
    assert cert.about_to_expire(14)

def test_not_about_to_expire():
    csr = _generate_csr('common-name', 'DNS:san1,DNS:san2')
    cert = bigacme.cert.Certificate.new('Common', 'test_not_about_to_expire', csr, 'http-01')
    cert.cert = _generate_certificate(-10800, 432000000)
    assert not cert.about_to_expire(14)

def test_save_when_owned_by_another_user(opt_user):
    """
    If a certificate is issued by another user than the one who is running the renew job
    the cert file will be owned by the issuing user. This should not fail as long as we
    own the folder and are able to re-create the file.

    Here we create a csr as root and then change to a normal user and try to save it again
    """
    if os.geteuid() != 0:
        pytest.skip("Not running as root")
    csr = _generate_csr('common-name', 'DNS:san1,DNS:san2')
    cert = bigacme.cert.Certificate.new('Common', 'test_save_when_owned_by_another_user', csr,
                                        'http-01')
    cert.save()
    uid = pwd.getpwnam(opt_user).pw_uid
    os.chown('.', uid, -1)
    # The folders must be owned be the correct user
    for folder in FOLDERS:
        os.chown(folder, uid, -1)
    os.setuid(uid)
    cert.save()
    assert os.path.isfile(cert.path)
