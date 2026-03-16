from src.db.session import SessionLocal
from src.db.models import User
import bcrypt

def reset_password():
    with SessionLocal() as db:
        admin = db.query(User).filter(User.username == "admin").first()
        if not admin:
            print("Admin user not found!")
            return
            
        password = "password123"
        hashed_password = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
        admin.hashed_password = hashed_password
        db.commit()
        print(f"Password for user '{admin.username}' reset successfully to 'password123'")

if __name__ == "__main__":
    reset_password()
