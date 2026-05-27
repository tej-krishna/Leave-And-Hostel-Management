from functools import wraps
from django.contrib import messages
from django.shortcuts import redirect

def role_required(allowed_roles):
    """
    Decorator for Django views to restrict access based on user role stored in session.
    Redirects to login if not authenticated, to dashboard/apply_leave if unauthorized.
    """
    def decorator(view_func):
        @wraps(view_func)
        def _wrapped_view(request, *args, **kwargs):
            user_role = request.session.get('user_role')

            if user_role in allowed_roles:
                return view_func(request, *args, **kwargs)
            elif not user_role:
                messages.error(request, "You need to log in to access this page.")
                return redirect('login')
            else:
                messages.error(request, "You do not have permission to access this page.")
                if user_role == 'student':
                    return redirect('apply_leave')
                else:
                    return redirect('dashboard')
        return _wrapped_view
    return decorator