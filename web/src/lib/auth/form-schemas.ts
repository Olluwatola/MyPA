import { z } from "zod";

// Rules mirror the backend's UserCreate so errors show instantly; the server's answer still wins.

function lowercaseDomain(email: string): string {
  const at = email.lastIndexOf("@");
  return email.slice(0, at) + email.slice(at).toLowerCase();
}

// Accept messy input (design-system.md §7.4): trim, lowercase the domain.
const email = z.string().trim().pipe(z.email("Enter a valid email address.")).transform(lowercaseDomain);

export const loginSchema = z.object({
  email,
  password: z.string().min(1, "Enter your password."),
});

export const signupSchema = z.object({
  firstName: z.string().trim().min(1, "Enter your first name.").max(30, "Use 30 characters or fewer."),
  lastName: z.string().trim().max(30, "Use 30 characters or fewer."),
  email,
  password: z.string().min(8, "Use at least 8 characters."),
});
