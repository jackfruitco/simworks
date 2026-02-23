// Profile Page Alpine.js Components

document.addEventListener('alpine:init', () => {
    // Alpine Store for profile data
    Alpine.store('profile', {
        first_name: document.getElementById('first-name-display')?.textContent || '',
        last_name: document.getElementById('last-name-display')?.textContent || '',
        bio: document.getElementById('bio-display')?.textContent || '',
    });
});

// Main profile data component
function profileData() {
    return {
        activeTab: 'profile',

        init() {
            // Initialize profile store with current values
            const firstNameEl = document.getElementById('first-name-display');
            const lastNameEl = document.getElementById('last-name-display');
            const bioEl = document.getElementById('bio-display');

            if (firstNameEl) Alpine.store('profile').first_name = firstNameEl.textContent;
            if (lastNameEl) Alpine.store('profile').last_name = lastNameEl.textContent;
            if (bioEl) Alpine.store('profile').bio = bioEl.textContent;
        },

        async updateField(fieldName, fieldValue) {
            try {
                const formData = new FormData();
                formData.append('field_name', fieldName);
                formData.append('field_value', fieldValue);
                formData.append('csrfmiddlewaretoken', getCsrfToken());

                const response = await fetch('/accounts/profile/update-field/', {
                    method: 'POST',
                    body: formData,
                    headers: {
                        'X-Requested-With': 'XMLHttpRequest',
                    }
                });

                if (!response.ok) {
                    throw new Error('Failed to update field');
                }

                const data = await response.json();

                // Update the display element
                const displayEl = document.getElementById(`${fieldName}-display`);
                if (displayEl) {
                    displayEl.textContent = data.field_value;
                }

                // Show success toast
                if (window.Alpine && window.Alpine.store('toasts')) {
                    window.Alpine.store('toasts').add('Profile updated successfully', 'success');
                }

            } catch (error) {
                console.error('Error updating field:', error);

                // Show error toast
                if (window.Alpine && window.Alpine.store('toasts')) {
                    window.Alpine.store('toasts').add('Failed to update profile', 'error');
                }
            }
        }
    };
}

// Simulation history data component
function simulationHistoryData() {
    return {
        filters: {
            status: '',
            sort: '-start_timestamp',
            lab_type: '',
            date_from: '',
            date_to: ''
        },
        loading: false,
        hasMore: true,
        simulationCount: 0,
        currentPage: 1,

        init() {
            // Load initial data
            this.loadSimulations();
        },

        async loadSimulations() {
            this.loading = true;

            try {
                const params = new URLSearchParams({
                    page: this.currentPage,
                    ...this.filters
                });

                // HTMX will handle the loading
                // This is just to track state

            } catch (error) {
                console.error('Error loading simulations:', error);
            } finally {
                this.loading = false;
            }
        },

        applyFilters() {
            this.currentPage = 1;
            this.buildQueryString();

            // Trigger HTMX reload
            const listContainer = document.getElementById('simulation-list');
            if (listContainer) {
                const url = `/accounts/profile/simulation-history/?${this.buildQueryString()}`;
                htmx.ajax('GET', url, {target: '#simulation-list', swap: 'innerHTML'});
            }
        },

        clearFilters() {
            this.filters = {
                status: '',
                sort: '-start_timestamp',
                lab_type: '',
                date_from: '',
                date_to: ''
            };
            this.applyFilters();
        },

        hasActiveFilters() {
            return this.filters.status !== '' ||
                   this.filters.lab_type !== '' ||
                   this.filters.date_from !== '' ||
                   this.filters.date_to !== '';
        },

        buildQueryString() {
            const params = new URLSearchParams();

            Object.keys(this.filters).forEach(key => {
                if (this.filters[key]) {
                    params.append(key, this.filters[key]);
                }
            });

            if (this.currentPage > 1) {
                params.append('page', this.currentPage);
            }

            return params.toString();
        },

        loadMore() {
            if (this.loading || !this.hasMore) return;

            this.currentPage++;
            this.loadSimulations();
        },

        handleScroll(event) {
            const element = event.target;
            const scrollThreshold = 0.9; // 90% scrolled

            if (element.scrollTop / (element.scrollHeight - element.clientHeight) > scrollThreshold) {
                this.loadMore();
            }
        }
    };
}

// Helper function to get CSRF token
function getCsrfToken() {
    const token = document.querySelector('[name=csrfmiddlewaretoken]');
    if (token) {
        return token.value;
    }

    // Fallback: try to get from cookie
    const cookies = document.cookie.split(';');
    for (let cookie of cookies) {
        const [name, value] = cookie.trim().split('=');
        if (name === 'csrftoken') {
            return value;
        }
    }

    return '';
}

// HTMX event handlers for profile updates
document.body.addEventListener('htmx:afterSwap', function(event) {
    // Re-initialize Alpine components after HTMX swaps
    if (event.detail.target.id === 'avatar-display') {
        // Show success toast for avatar upload
        if (window.Alpine && window.Alpine.store('toasts')) {
            window.Alpine.store('toasts').add('Avatar updated successfully', 'success');
        }
    }
});

document.body.addEventListener('htmx:responseError', function(event) {
    // Show error toast on HTMX errors
    if (window.Alpine && window.Alpine.store('toasts')) {
        window.Alpine.store('toasts').add('An error occurred. Please try again.', 'error');
    }
});
