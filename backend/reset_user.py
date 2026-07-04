import sys
import os

# Insert backend path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from auth_db import _get_conn

def reset_user(email="sumit@meldra.ai"):
    conn = _get_conn()
    try:
        cur = conn.cursor()
        # Delete pending MFA tokens
        cur.execute("""
            DELETE FROM auth.mfa_tokens 
            WHERE user_id IN (SELECT id FROM auth.users WHERE email = %s)
        """, (email,))
        
        # Delete user
        cur.execute("DELETE FROM auth.users WHERE email = %s", (email,))
        conn.commit()
        print(f"Successfully deleted user '{email}' and cleared pending tokens. You can now re-register!")
    except Exception as e:
        print(f"Error resetting user: {e}")
        conn.rollback()
    finally:
        conn.close()

if __name__ == "__main__":
    reset_user()
