import bcrypt

def hash_password(password: str) -> str:
    if not password:
        raise ValueError("Password must not be empty")
    salt = bcrypt.gensalt()
    hashed = bcrypt.hashpw(password.encode("utf-8"), salt)
    return hashed.decode("utf-8")

def verify_password(password: str, hashed_password: str) -> bool:
    if not password or not hashed_password:
        return False
    return bcrypt.checkpw(password.encode("utf-8"), hashed_password.encode("utf-8"))
