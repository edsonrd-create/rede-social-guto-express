"""Generate a private local env file; never print credentials or overwrite an existing file."""
import os
import secrets
from cryptography.fernet import Fernet
from owner_auth import password_hash

if __name__=='__main__':
    password=secrets.token_urlsafe(32)
    target='deployment-secrets.env'
    fd=os.open(target,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(fd,'w') as f:
        f.write('TOKEN_ENCRYPTION_KEY='+Fernet.generate_key().decode()+'\n')
        f.write('OWNER_PASSWORD_HASH='+password_hash(password)+'\n')
        f.write('OWNER_LOGIN_PASSWORD='+password+'\n')
    print('Arquivo privado criado. Configure somente TOKEN_ENCRYPTION_KEY e OWNER_PASSWORD_HASH no servidor; mantenha OWNER_LOGIN_PASSWORD no seu gerenciador de senhas.')
