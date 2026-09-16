from django import template

register = template.Library()

# Maps every status/stage string used across Student.status,
# LeaveApplication.status and LeaveApplication.current_stage to one of the
# five semantic badge colors defined in components.css. Centralized here so
# every template gets the same color for the same meaning instead of each
# page inventing its own badge markup.
_BADGE_MAP = {
    'present': 'success',
    'approved': 'success',
    'completed': 'success',
    'verified': 'success',
    'leave': 'info',
    'outing': 'info',
    'out': 'info',
    'gate_in': 'info',
    'rejected': 'danger',
    'verification_failed': 'danger',
    'failed': 'danger',
    'pending': 'warning',
    'warden': 'warning',
    'caretaker': 'warning',
    'chief_warden': 'warning',
    'dsw': 'warning',
    'dean': 'warning',
    'ao': 'warning',
    'director': 'warning',
    'caretaker_verification': 'warning',
    'cleared_for_departure': 'warning',
    'not_required': 'neutral',
    'sent': 'success',
}


@register.filter
def badge_class(value):
    """`{{ leave.status|badge_class }}` -> 'badge-success' etc."""
    key = str(value).strip().lower()
    return 'badge-' + _BADGE_MAP.get(key, 'neutral')


@register.filter
def initial(value):
    """First character, uppercased - for avatar circles."""
    text = str(value or '').strip()
    return text[0].upper() if text else '?'
