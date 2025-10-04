import uuid
import random
import string
import time
from datetime import datetime


def generate_random_string(length=10, include_digits=True, include_uppercase=True, include_lowercase=True):
    """
    Generate a random string with customizable character sets
    
    Args:
        length (int): Length of the random string to generate
        include_digits (bool): Include digits in the random string
        include_uppercase (bool): Include uppercase letters in the random string
        include_lowercase (bool): Include lowercase letters in the random string
        
    Returns:
        str: Random string
    """
    chars = ''
    
    if include_digits:
        chars += string.digits
    if include_uppercase:
        chars += string.ascii_uppercase
    if include_lowercase:
        chars += string.ascii_lowercase
        
    if not chars:
        chars = string.ascii_uppercase + string.digits
        
    return ''.join(random.choice(chars) for _ in range(length))


def generate_transaction_reference(prefix='TRX'):
    """
    Generate a unique transaction reference
    
    Args:
        prefix (str): Prefix for the reference
        
    Returns:
        str: Unique transaction reference
    """
    timestamp = int(time.time())
    random_str = generate_random_string(6)
    return f"{prefix}{timestamp}{random_str}"


def generate_settlement_reference(prefix='STL'):
    """
    Generate a unique settlement reference
    
    Args:
        prefix (str): Prefix for the reference
        
    Returns:
        str: Unique settlement reference
    """
    timestamp = int(time.time())
    random_str = generate_random_string(6)
    return f"{prefix}{timestamp}{random_str}"


def generate_charge_reference(prefix='CHG'):
    """
    Generate a unique charge reference
    
    Args:
        prefix (str): Prefix for the reference
        
    Returns:
        str: Unique charge reference
    """
    timestamp = int(time.time())
    random_str = generate_random_string(6)
    return f"{prefix}{timestamp}{random_str}"   #is CHG USEFULL, DECEIDED TO KEEP IT


def generate_transfer_reference(prefix='TRF'):
    """
    Generate a unique transfer reference
    
    Args:
        prefix (str): Prefix for the reference
        
    Returns:
        str: Unique transfer reference
    """
    timestamp = int(time.time())
    random_str = generate_random_string(6)
    return f"{prefix}{timestamp}{random_str}"


def generate_wallet_tag(user):
    """
    Generate a wallet tag for a user
    
    Args:
        user: User instance
        
    Returns:
        str: Wallet tag
    """
    # Create a tag from the user's username or email
    username = getattr(user, 'username', None)
    email = getattr(user, 'email', None)
    
    if username:
        base = username
    elif email:
        base = email.split('@')[0]
    else:
        base = str(uuid.uuid4())[:8]
        
    # Sanitize the base string
    base = ''.join(c for c in base if c.isalnum())
    
    # Ensure the tag is unique by adding a timestamp if needed
    if len(base) < 5:
        timestamp = datetime.now().strftime('%H%M%S')
        return f"{base}{timestamp}"
    
    return base[:15]  # Limit to 15 characters