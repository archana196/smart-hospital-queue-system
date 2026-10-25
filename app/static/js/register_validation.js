/**
 * register_validation.js
 *
 * Client-side validation for the patient registration form.
 * PURPOSE: smooth UX — show inline errors before the round-trip.
 * SECURITY NOTE: This JavaScript is NOT authoritative. The Flask backend
 * (ValidationService) re-validates every field independently.
 * Disabling or bypassing this script does NOT bypass server validation.
 */

'use strict';

document.addEventListener('DOMContentLoaded', function () {

    // ── Element references ──────────────────────────────────────────────────
    const form        = document.getElementById('registrationForm');
    const nameInput   = document.getElementById('name');
    const ageInput    = document.getElementById('age');
    const genderSel   = document.getElementById('gender');
    const phoneInput  = document.getElementById('phone');
    const deptSel     = document.getElementById('department_id');
    const prioritySel = document.getElementById('priority');

    const regTypeOnline = document.getElementById('regTypeOnline');
    const regTypeWalkin = document.getElementById('regTypeWalkin');
    const apptContainer = document.getElementById('appointmentFields');
    const apptDateInput = document.getElementById('appointment_date');
    const apptTimeInput = document.getElementById('appointment_time');

    // ── Constants matching Python ValidationService ─────────────────────────
    const NAME_MIN     = 2;
    const NAME_MAX     = 100;
    const NAME_PATTERN = /^[A-Za-z\u00C0-\u024F\u0900-\u097F\s'\-]+$/u;
    const PHONE_PATTERN = /^\d{10}$/;
    const AGE_MIN      = 1;
    const AGE_MAX      = 120;

    // ── Online/Walk-in toggle ───────────────────────────────────────────────
    function toggleAppointmentFields() {
        const isOnline = regTypeOnline && regTypeOnline.checked;
        if (apptContainer) {
            apptContainer.style.display = isOnline ? 'block' : 'none';
        }
        if (apptDateInput) apptDateInput.required = isOnline;
        if (apptTimeInput) apptTimeInput.required = isOnline;
        if (!isOnline) {
            if (apptDateInput) apptDateInput.value = '';
            if (apptTimeInput) apptTimeInput.value = '';
        }
    }

    if (regTypeOnline && regTypeWalkin) {
        regTypeOnline.addEventListener('change', toggleAppointmentFields);
        regTypeWalkin.addEventListener('change', toggleAppointmentFields);
        toggleAppointmentFields(); // run on page load
    }

    // ── Helper: set valid / invalid state on a field ────────────────────────
    function setValid(el) {
        el.classList.remove('is-invalid');
        el.classList.add('is-valid');
        const fb = el.parentElement.querySelector('.invalid-feedback') ||
                   el.closest('.col-md-6, .col-md-3, .col-md-4, .mb-4')
                     ?.querySelector('.invalid-feedback');
        if (fb) fb.style.display = 'none';
    }

    function setInvalid(el, message) {
        el.classList.remove('is-valid');
        el.classList.add('is-invalid');
        // Find or create an invalid-feedback element
        let fb = el.parentElement.querySelector('.invalid-feedback');
        if (!fb) {
            // For input-group (phone), look one level up
            fb = el.closest('.input-group')?.parentElement?.querySelector('.invalid-feedback');
        }
        if (!fb) {
            fb = document.createElement('div');
            fb.className = 'invalid-feedback';
            el.insertAdjacentElement('afterend', fb);
        }
        fb.innerHTML = '<i class="fa-solid fa-circle-exclamation me-1"></i>' + message;
        fb.style.display = 'block';
    }

    function clearState(el) {
        el.classList.remove('is-valid', 'is-invalid');
    }

    // ── Individual field validators ─────────────────────────────────────────

    function validateName() {
        const val = nameInput.value.trim();
        if (!val) {
            setInvalid(nameInput, 'Full name is required.');
            return false;
        }
        if (val.length < NAME_MIN) {
            setInvalid(nameInput, `Name must be at least ${NAME_MIN} characters.`);
            return false;
        }
        if (val.length > NAME_MAX) {
            setInvalid(nameInput, `Name must not exceed ${NAME_MAX} characters.`);
            return false;
        }
        if (!NAME_PATTERN.test(val)) {
            setInvalid(nameInput,
                'Name may only contain letters, spaces, hyphens, and apostrophes — no digits or special characters.');
            return false;
        }
        setValid(nameInput);
        return true;
    }

    function validateAge() {
        const raw = ageInput.value.trim();
        if (!raw) {
            setInvalid(ageInput, 'Age is required.');
            return false;
        }
        const age = parseInt(raw, 10);
        if (isNaN(age) || !Number.isInteger(age)) {
            setInvalid(ageInput, 'Age must be a whole number.');
            return false;
        }
        if (age < AGE_MIN || age > AGE_MAX) {
            setInvalid(ageInput, `Age must be between ${AGE_MIN} and ${AGE_MAX}.`);
            return false;
        }
        setValid(ageInput);
        return true;
    }

    function validateGender() {
        const val = genderSel.value;
        if (!val) {
            setInvalid(genderSel, 'Please select a gender.');
            return false;
        }
        setValid(genderSel);
        return true;
    }

    function validatePhone() {
        const val = phoneInput.value.trim();
        if (!val) {
            setInvalid(phoneInput, 'Phone number is required.');
            return false;
        }
        if (!PHONE_PATTERN.test(val)) {
            setInvalid(phoneInput,
                'Phone number must be exactly 10 digits (Indian mobile number, e.g. 9876543210).');
            return false;
        }
        setValid(phoneInput);
        return true;
    }

    function validateDepartment() {
        const val = deptSel.value;
        if (!val) {
            setInvalid(deptSel, 'Please select a department.');
            return false;
        }
        setValid(deptSel);
        return true;
    }

    function validateAppointmentFields() {
        const isOnline = regTypeOnline && regTypeOnline.checked;
        if (!isOnline) return true;

        let ok = true;
        if (!apptDateInput.value) {
            setInvalid(apptDateInput, 'Appointment date is required for Online registration.');
            ok = false;
        } else {
            setValid(apptDateInput);
        }
        if (!apptTimeInput.value) {
            setInvalid(apptTimeInput, 'Appointment time is required for Online registration.');
            ok = false;
        } else {
            setValid(apptTimeInput);
        }
        return ok;
    }

    // ── Live validation (blur events) ───────────────────────────────────────
    nameInput?.addEventListener('blur', validateName);
    nameInput?.addEventListener('input', function () {
        if (nameInput.classList.contains('is-invalid')) validateName();
    });

    ageInput?.addEventListener('blur', validateAge);
    ageInput?.addEventListener('input', function () {
        if (ageInput.classList.contains('is-invalid')) validateAge();
    });

    genderSel?.addEventListener('change', validateGender);

    phoneInput?.addEventListener('blur', validatePhone);
    phoneInput?.addEventListener('input', function () {
        // Only allow digits while typing
        phoneInput.value = phoneInput.value.replace(/\D/g, '').slice(0, 10);
        if (phoneInput.classList.contains('is-invalid')) validatePhone();
    });

    deptSel?.addEventListener('change', validateDepartment);

    apptDateInput?.addEventListener('change', validateAppointmentFields);
    apptTimeInput?.addEventListener('change', validateAppointmentFields);

    // ── Full-form validation on submit ──────────────────────────────────────
    form?.addEventListener('submit', function (e) {
        const results = [
            validateName(),
            validateAge(),
            validateGender(),
            validatePhone(),
            validateDepartment(),
            validateAppointmentFields(),
        ];

        const allOk = results.every(Boolean);
        if (!allOk) {
            e.preventDefault();
            // Scroll to first error
            const firstInvalid = form.querySelector('.is-invalid');
            if (firstInvalid) {
                firstInvalid.scrollIntoView({ behavior: 'smooth', block: 'center' });
                firstInvalid.focus();
            }
        }
    });

    // ── Phone: block non-digit keystrokes ───────────────────────────────────
    phoneInput?.addEventListener('keydown', function (e) {
        const allowed = ['Backspace', 'Delete', 'ArrowLeft', 'ArrowRight',
                          'Tab', 'Enter', 'Home', 'End'];
        if (!allowed.includes(e.key) && !/^\d$/.test(e.key)) {
            e.preventDefault();
        }
    });
});
