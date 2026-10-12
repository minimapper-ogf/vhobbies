# ---- Village Hobbies Racing site settings ----
import os
BASE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE, 'data', 'vhr.db')
UPLOAD_DIR = os.path.join(BASE, 'static', 'uploads')          # public, approved images
PENDING_DIR = os.path.join(BASE, 'data', 'pending_photos')    # not public: waiting for approval

SITE_NAME = "Village Hobbies Racing"
SITE_TAGLINE = "Hesperia, Michigan"

# Used by the admin panel. CHANGE THESE.
ADMIN_USERNAME = "user1"
ADMIN_PASSWORD = "pass1"
# Set ADMIN_PASSWORD_2 to enable the second account.
ADMIN_USERNAME_2 = "user2"
ADMIN_PASSWORD_2 = "pass2"
SECRET_KEY = "key"

# True = errors shown, False = no errors shown
DEBUG = False
