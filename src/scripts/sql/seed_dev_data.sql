-- Sample development data for PostgreSQL
-- Created: 2025-11-17
-- Database: lupin_auth

-- Insert test users
-- Password for all test users: "TestPassword123!"
-- Hash generated with: python -c "from passlib.hash import bcrypt; print(bcrypt.hash('TestPassword123!'))"

INSERT INTO users (id, email, password_hash, created_at, email_verified, is_active, roles)
VALUES
    (gen_random_uuid(), 'test@example.com', '$2b$12$KIXfF5z6Z0VqF5Z6Z0VqF.VqF5Z6Z0VqF5Z6Z0VqF5Z6Z0VqF5Z6Zu', NOW(), TRUE, TRUE, '["user"]'::jsonb),
    (gen_random_uuid(), 'admin@example.com', '$2b$12$KIXfF5z6Z0VqF5Z6Z0VqF.VqF5Z6Z0VqF5Z6Z0VqF5Z6Z0VqF5Z6Zu', NOW(), TRUE, TRUE, '["admin", "user"]'::jsonb),
    (gen_random_uuid(), 'inactive@example.com', '$2b$12$KIXfF5z6Z0VqF5Z6Z0VqF.VqF5Z6Z0VqF5Z6Z0VqF5Z6Z0VqF5Z6Zu', NOW(), FALSE, FALSE, '["user"]'::jsonb)
ON CONFLICT (email) DO NOTHING;

-- Note: These are development-only test users
-- The password hash above is a placeholder - actual bcrypt hashes should be generated
-- For production, never commit real user credentials
