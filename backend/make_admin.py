"""
Promote a user to admin or demote back to client.

Usage:
    python make_admin.py <email>              # promote to admin
    python make_admin.py <email> --demote     # demote to client
    python make_admin.py --list               # list all admins
"""
import sys
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

DATABASE_URL = "sqlite:///./leadgen.db"
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
Session = sessionmaker(bind=engine)


def list_admins():
    with Session() as s:
        rows = s.execute(text("SELECT email, name, role FROM users WHERE role = 'admin'")).fetchall()
    if not rows:
        print("No admins found.")
        return
    print(f"{'EMAIL':<40} {'NAME':<30} {'ROLE':<10}")
    print("-" * 80)
    for r in rows:
        print(f"{r[0]:<40} {r[1] or '':<30} {r[2]:<10}")


def set_role(email: str, role: str):
    with Session() as s:
        user = s.execute(text("SELECT id, email, role FROM users WHERE email = :e"), {"e": email}).fetchone()
        if not user:
            print(f"ERROR: No user with email '{email}'. Register via the website first.")
            sys.exit(1)
        s.execute(text("UPDATE users SET role = :r WHERE email = :e"), {"r": role, "e": email})
        s.commit()
        print(f"OK: {email} role set to '{role}'.")


if __name__ == "__main__":
    args = sys.argv[1:]
    if not args or args[0] in ("-h", "--help"):
        print(__doc__)
        sys.exit(0)
    if args[0] == "--list":
        list_admins()
    elif len(args) == 2 and args[1] == "--demote":
        set_role(args[0], "client")
    else:
        set_role(args[0], "admin")
