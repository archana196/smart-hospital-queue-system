document.addEventListener('DOMContentLoaded', function () {
    const regTypeOnline = document.getElementById('regTypeOnline');
    const regTypeWalkin = document.getElementById('regTypeWalkin');
    const apptFieldsContainer = document.getElementById('appointmentFields');
    const apptDateInput = document.getElementById('appointment_date');
    const apptTimeInput = document.getElementById('appointment_time');

    function toggleAppointmentFields() {
        if (regTypeOnline && regTypeOnline.checked) {
            apptFieldsContainer.style.display = 'block';
            apptDateInput.required = true;
            apptTimeInput.required = true;
        } else if (regTypeWalkin && regTypeWalkin.checked) {
            apptFieldsContainer.style.display = 'none';
            apptDateInput.required = false;
            apptTimeInput.required = false;
            apptDateInput.value = '';
            apptTimeInput.value = '';
        }
    }

    if (regTypeOnline && regTypeWalkin) {
        regTypeOnline.addEventListener('change', toggleAppointmentFields);
        regTypeWalkin.addEventListener('change', toggleAppointmentFields);
        toggleAppointmentFields(); // Initial check on load
    }
});
