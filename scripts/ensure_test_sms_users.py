"""One-off: ensure test agent + customer exist for SMS UAT."""
import django

django.setup()

from core.models import MyUser
from core.phone_utils import normalize_kenya_phone

SPECS = [
    {
        'role': 'Field Agent',
        'phone_raw': '0706922731',
        'email': 'agent.test706922731@metrolinks.local',
        'first_name': 'Test',
        'last_name': 'Agent',
        'password': 'TestAgent123!',
    },
    {
        'role': 'Customer',
        'phone_raw': '0742134431',
        'email': 'customer.test742134431@metrolinks.local',
        'first_name': 'Test',
        'last_name': 'Customer',
        'password': 'TestCustomer123!',
    },
]

for spec in SPECS:
    phone = normalize_kenya_phone(spec['phone_raw'])
    existing = MyUser.objects.filter(phone=phone).first()
    if not existing:
        existing = MyUser.objects.filter(phone__icontains=spec['phone_raw'][-9:]).first()

    if existing:
        updates = []
        if existing.role != spec['role']:
            existing.role = spec['role']
            updates.append('role')
        if existing.phone != phone:
            existing.phone = phone
            updates.append('phone')
        if updates:
            existing.save(update_fields=updates)
        print(
            f"EXISTS — {spec['role']}: id={existing.pk}, "
            f"email={existing.email}, phone={existing.phone}"
        )
    else:
        user = MyUser.objects.create_user(
            email=spec['email'],
            password=spec['password'],
            first_name=spec['first_name'],
            last_name=spec['last_name'],
            phone=spec['phone_raw'],
            role=spec['role'],
        )
        print(
            f"CREATED — {spec['role']}: id={user.pk}, "
            f"email={user.email}, phone={user.phone}, "
            f"password={spec['password']}"
        )
