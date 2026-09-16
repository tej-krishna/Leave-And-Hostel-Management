# HostelManagement/hostel_app/forms.py

from django import forms
from .models import LeaveApplication, Student
from django.utils import timezone


def _apply_input_css_classes(form):
    """
    Adds the design system's .input/.select CSS class to every visible
    field's widget, without each field having to declare it individually.
    Purely a presentation hook (static/css/components.css) - no effect on
    validation or submitted data.
    """
    for field in form.fields.values():
        widget = field.widget
        if isinstance(widget, forms.CheckboxInput):
            continue
        css_class = 'select' if isinstance(widget, (forms.Select, forms.SelectMultiple)) else 'input'
        existing = widget.attrs.get('class', '')
        widget.attrs['class'] = (existing + ' ' + css_class).strip()


class StudentForm(forms.ModelForm):
    class Meta:
        model = Student
        fields = [
            'name', 'student_id', 'gender', 'dob', 'mobile_number',
            'university_email', 'personal_email', 'year', 'branch',
            'hostel', 'room', 'parent_name', 'parent_mobile',
            'blood_group', 'address', 'role'
        ]
        widgets = {
            'dob': forms.DateInput(attrs={'type': 'date'}),
            'address': forms.Textarea(attrs={'rows': 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _apply_input_css_classes(self)

class LeaveApplicationForm(forms.ModelForm):

    # Using DateTimeInput with type='datetime-local' for better browser support
    out_time = forms.DateTimeField(
        widget=forms.DateTimeInput(attrs={'type': 'datetime-local'}),
        help_text="Expected date and time of departure."
    )
    in_time = forms.DateTimeField(
        widget=forms.DateTimeInput(attrs={'type': 'datetime-local'}),
        help_text="Expected date and time of return."
    )

    # Use CharField with a datalist for searching
    companion_id = forms.CharField(
        required=False,
        label="Select Companion (Search by ID or Name)",
        help_text="Start typing the student's ID or name.",
        widget=forms.TextInput(attrs={'list': 'student-list', 'placeholder': 'Type to search student...'})
    )

    class Meta:
        model = LeaveApplication
        fields = ['leave_type', 'out_time', 'in_time', 'reason', 'parent_coming', 'approval_of']
        labels = {
            'leave_type': 'Application Type',
            'out_time': 'Expected Departure Time',
            'in_time': 'Expected Return Time',
            'reason': 'Reason for Leave/Outing',
            'parent_coming': 'My Parent is Coming',
            'approval_of': 'Approval Of (Optional)',
        }
        widgets = {
            'reason': forms.Textarea(attrs={'rows': 4, 'placeholder': 'Briefly describe your reason for leave/outing...'}),
            'approval_of': forms.TextInput(attrs={'placeholder': 'E.g., Warden, Parent...'}),
        }

    def __init__(self, *args, **kwargs):
        self.student = kwargs.pop('student', None)
        super().__init__(*args, **kwargs)
        _apply_input_css_classes(self)

        if self.student:
            # Male students cannot have parents come
            if self.student.gender == 'M':
                # Remove parent_coming field from visible fields
                self.fields['parent_coming'].widget = forms.HiddenInput()
                self.fields['parent_coming'].initial = False
            
            # For female students, all years can have parents come (allowed)
            # The restriction for P1-E2 is handled in clean()

    def clean_companion_id(self):
        companion_id = self.cleaned_data.get('companion_id')
        if not companion_id:
            return None
            
        # The datalist might provide "Name (ID)", we need to extract the ID
        import re
        match = re.search(r'\((.*?)\)', companion_id)
        search_id = match.group(1) if match else companion_id
        
        try:
            companion = Student.objects.get(student_id__iexact=search_id)
            if self.student and companion.pk == self.student.pk:
                raise forms.ValidationError("You cannot select yourself as a companion.")
            return companion
        except Student.DoesNotExist:
            # Maybe they just typed the name, but we need exact ID for safety
            raise forms.ValidationError(f"Could not find a student with ID '{search_id}'. Please select from the list.")

    def clean(self):
        cleaned_data = super().clean()
        out_time = cleaned_data.get('out_time')
        in_time = cleaned_data.get('in_time')
        parent_coming = cleaned_data.get('parent_coming')
        companion = cleaned_data.get('companion_id') # This is now the Student object from clean_companion_id

        # 1. Basic time validation
        if out_time and in_time:
            if out_time >= in_time:
                self.add_error('in_time', "Return time must be after departure time.")
            
            now = timezone.now()
            if out_time < now and out_time.date() < now.date(): 
                 self.add_error('out_time', "Departure time cannot be in the past for a new application.")

        # 2. Safety Logic Rules
        if self.student:
            # Male students parent_coming is always False
            if self.student.gender == 'M':
                cleaned_data['parent_coming'] = False
                parent_coming = False
            
            # Restricted student validation (Girls P1-E2)
            if self.student.gender == 'F' and self.student.year not in ['E3', 'E4']:
                if not parent_coming and not companion:
                    raise forms.ValidationError(
                        "For your safety, students in your year must either have their own parent coming "
                        "or specify a companion whose parent is coming."
                    )
            
            if companion:
                # Check if companion has an active leave application
                from .models import LeaveApplication
                overlapping_companion_leave = LeaveApplication.objects.filter(
                    student=companion,
                    status__in=['pending', 'approved'],
                    out_time__date=out_time.date() if out_time else None
                ).exists()

                if not overlapping_companion_leave:
                    self.add_error('companion_id', 
                        f"{companion.name} does not have a leave application for this date. "
                        "Both students must apply for leave for a group leave to be valid."
                    )
                
                # Set the companion field on the model instance
                self.instance.companion = companion

        return cleaned_data