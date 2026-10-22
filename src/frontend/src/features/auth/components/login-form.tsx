import { useState } from "react"
import { useForm } from "react-hook-form"
import { zodResolver } from "@hookform/resolvers/zod"
import { Eye, EyeOff, LoaderCircle } from "lucide-react"
import { toast } from "sonner"

import { Alert } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { ApiError } from "@/lib/api"

import { useLogin } from "../hooks"
import { loginSchema, type LoginFormValues } from "../schema"
import { ForgotPassword } from "./forgot-password"

function errorMessage(error: unknown): string | null {
  if (!error) return null
  if (error instanceof ApiError) return error.message
  return "Something went wrong. Please try again."
}

export function LoginForm() {
  const login = useLogin()
  const [showPassword, setShowPassword] = useState(false)
  const [forgot, setForgot] = useState(false)
  const {
    register,
    handleSubmit,
    setFocus,
    resetField,
    formState: { errors },
  } = useForm<LoginFormValues>({
    resolver: zodResolver(loginSchema),
    defaultValues: { email: "", password: "" },
    mode: "onTouched",
  })

  // Redirect after success is handled by <GuestOnly> once the user is cached
  const onSubmit = handleSubmit((values) =>
    login.mutate(values, {
      onError: () => {
        resetField("password")
        setFocus("password")
      },
    }),
  )

  if (forgot) {
    return (
      <div className="mt-10">
        <ForgotPassword onDone={() => setForgot(false)} />
      </div>
    )
  }

  const serverError = errorMessage(login.error)

  return (
    <>
      <form onSubmit={onSubmit} noValidate className="mt-10 space-y-5" aria-label="Sign in">
        {serverError && <Alert>{serverError}</Alert>}

        <div className="space-y-2">
          <Label htmlFor="email">Work email</Label>
          <Input
            id="email"
            type="email"
            inputMode="email"
            autoComplete="username"
            autoFocus
            placeholder="name@company.com"
            aria-invalid={errors.email ? true : undefined}
            aria-describedby={errors.email ? "email-error" : undefined}
            {...register("email")}
          />
          {errors.email && (
            <p id="email-error" className="text-sm text-destructive">
              {errors.email.message}
            </p>
          )}
        </div>

        <div className="space-y-2">
          <Label htmlFor="password">Password</Label>
          <div className="relative">
            <Input
              id="password"
              type={showPassword ? "text" : "password"}
              autoComplete="current-password"
              className="pr-11"
              aria-invalid={errors.password ? true : undefined}
              aria-describedby={errors.password ? "password-error" : undefined}
              {...register("password")}
            />
            <button
              type="button"
              onClick={() => setShowPassword((v) => !v)}
              className="absolute inset-y-0 right-0 flex w-11 items-center justify-center rounded-r-md text-muted-foreground hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
              aria-label={showPassword ? "Hide password" : "Show password"}
              aria-pressed={showPassword}
            >
              {showPassword ? <EyeOff className="size-4" /> : <Eye className="size-4" />}
            </button>
          </div>
          {errors.password && (
            <p id="password-error" className="text-sm text-destructive">
              {errors.password.message}
            </p>
          )}
        </div>

        <Button type="submit" size="lg" className="mt-2 w-full px-4 font-semibold" disabled={login.isPending}>
          {login.isPending ? (
            <>
              <LoaderCircle className="animate-spin" aria-hidden />
              Signing in…
            </>
          ) : (
            "Sign in"
          )}
        </Button>
      </form>

      <div className="mt-6 flex flex-col items-start gap-y-2 text-sm text-muted-foreground sm:flex-row sm:items-center sm:gap-x-3">
        <button
          type="button"
          className="underline-offset-4 hover:text-foreground hover:underline"
          onClick={() =>
            toast.info("Single sign-on isn't configured yet", {
              description: "Microsoft Entra ID SSO is planned for a later phase. Sign in with your work email.",
            })
          }
        >
          SSO with Microsoft Entra ID
        </button>
        <span aria-hidden className="hidden sm:inline">
          |
        </span>
        <button
          type="button"
          className="underline-offset-4 hover:text-foreground hover:underline"
          onClick={() => setForgot(true)}
        >
          Forgot password?
        </button>
      </div>
    </>
  )
}
