/**
 * Admin Dashboard - JavaScript Logic
 *
 * Handles:
 * - JWT authentication check
 * - Admin role verification
 * - User info display
 * - Logout functionality
 */

class AdminDashboard {
    constructor() {
        this.userEmailElement = document.getElementById( 'userEmail' );
        this.logoutBtn = document.getElementById( 'logoutBtn' );

        this.init();
    }

    async init() {
        // Check authentication and admin role
        await this.checkAuth();

        // Set up event listeners
        this.setupEventListeners();
    }

    async checkAuth() {
        try {
            // Check if user is authenticated
            if ( !isAuthenticated() ) {
                window.location.href = '/static/html/auth/login.html';
                return;
            }

            // Get current user data (uses auth.js function)
            const userData = await getCurrentUser();

            if ( !userData ) {
                // Failed to get user data - redirect to login
                clearTokens();
                window.location.href = '/static/html/auth/login.html';
                return;
            }

            // Check admin role
            const isAdmin = await hasRole( 'admin' );
            if ( !isAdmin ) {
                // Not an admin - redirect to profile with error message
                alert( 'Access denied: Admin role required' );
                window.location.href = '/static/html/auth/profile.html';
                return;
            }

            // Display user email
            this.displayUserInfo( userData );

        } catch ( error ) {
            console.error( 'Authentication check failed:', error );
            clearTokens();
            window.location.href = '/static/html/auth/login.html';
        }
    }

    displayUserInfo( userData ) {
        if ( this.userEmailElement && userData.email ) {
            this.userEmailElement.textContent = userData.email;
        }
    }

    setupEventListeners() {
        // Logout button
        if ( this.logoutBtn ) {
            this.logoutBtn.addEventListener( 'click', () => {
                this.handleLogout();
            });
        }
    }

    handleLogout() {
        // Clear tokens
        clearTokens();

        // Redirect to login page
        window.location.href = '/static/html/auth/login.html';
    }
}

// Initialize dashboard when DOM is ready
document.addEventListener( 'DOMContentLoaded', () => {
    new AdminDashboard();
});
