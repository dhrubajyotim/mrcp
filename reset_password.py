"""
Usage:
  python reset_password.py <email> <new_password>

Example:
  python reset_password.py test@test.com mynewpass123
"""
import sys
from passlib.context import CryptContext
import sqlite3

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

if len(sys.argv) != 3:
    print("Usage: python reset_password.py <email> <new_password>")
    sys.exit(1)

email, new_password = sys.argv[1], sys.argv[2]

c = sqlite3.connect('mcq.db')
user = c.execute("SELECT id FROM users WHERE email=?", (email,)).fetchone()
if not user:
    print(f"No user found with email: {email}")
    c.close()
    sys.exit(1)

new_hash = pwd_context.hash(new_password)
c.execute("UPDATE users SET hashed_password=? WHERE email=?", (new_hash, email))
c.commit()
print(f"Password reset for {email}")
c.close()
