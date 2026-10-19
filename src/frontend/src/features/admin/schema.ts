import { z } from "zod"

// Mirrors PASSWORD_MIN_LENGTH in src/app/users/schemas.py
export const PASSWORD_MIN_LENGTH = 12

const password = z
  .string()
  .min(PASSWORD_MIN_LENGTH, `Use at least ${PASSWORD_MIN_LENGTH} characters`)
  .max(256, "Use at most 256 characters")

const fullName = z.string().trim().min(1, "Enter a name").max(200, "Use at most 200 characters")

export const createUserSchema = z.object({
  full_name: fullName,
  // refine, not .pipe(z.email()): the piped output type makes `email` optional
  email: z
    .string()
    .trim()
    .min(1, "Enter an email")
    .refine((value) => z.email().safeParse(value).success, "Enter a valid email address"),
  role: z.enum(["finance_admin", "user"]),
  password,
})

export type CreateUserValues = z.infer<typeof createUserSchema>

export const profileSchema = z.object({
  full_name: fullName,
  role: z.enum(["finance_admin", "user"]),
})

export type ProfileValues = z.infer<typeof profileSchema>

export const passwordSchema = z.object({ password })

export type PasswordValues = z.infer<typeof passwordSchema>
