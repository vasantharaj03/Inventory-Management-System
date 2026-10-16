"""Lists every login and lets you reset a password (or create an admin).
Run from the backend folder:  py reset_admin.py
"""
from sqlalchemy import text
from main import engine, hash_pw

with engine.begin() as c:
    users = c.execute(text("SELECT id,name,email,role,is_active FROM users ORDER BY id")).mappings().all()
    print("\nAccounts in the database:")
    if not users:
        print("  (none yet)")
    for u in users:
        print(f"  {u['id']}: {u['email']}   role={u['role']}   active={u['is_active']}   name={u['name']}")

    email = input("\nEmail to reset or create (press Enter for admin@stockroom.com): ").strip().lower() or "admin@stockroom.com"
    pw = input("New password (at least 6 characters): ").strip()
    if len(pw) < 6:
        raise SystemExit("Password is too short. Nothing was changed.")
    ph = hash_pw(pw)
    row = c.execute(text("SELECT id,role FROM users WHERE email=:e"), {"e": email}).first()
    if row:
        make_admin = row[1] != "admin" and input("This account is not an admin. Make it an admin? (y/n): ").strip().lower() == "y"
        c.execute(text("UPDATE users SET password_hash=:p, is_active=1, role=IF(:a, 'admin', role) WHERE email=:e"),
                  {"p": ph, "e": email, "a": 1 if make_admin else 0})
        print(f"\nDone. Password updated for {email}. The account is active.")
    else:
        c.execute(text("INSERT INTO users (name,email,password_hash,role) VALUES ('Admin',:e,:p,'admin')"), {"e": email, "p": ph})
        print(f"\nDone. Created a new admin account: {email}")
print("Sign in on the ADMIN tab with this email and password.")