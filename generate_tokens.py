# Very quick script to generate tokens to use with SPRE
import secrets

tokensize = 32

print(secrets.token_hex(tokensize))
print(secrets.token_hex(tokensize))
print(secrets.token_hex(tokensize))
print(secrets.token_hex(tokensize))
