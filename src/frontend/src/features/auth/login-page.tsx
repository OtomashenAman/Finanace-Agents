import { BrandPanel } from "./components/brand-panel"
import { LoginForm } from "./components/login-form"

export function LoginPage() {
  return (
    <div className="flex min-h-svh flex-col items-center justify-center bg-brand-page px-4 py-8 sm:px-8">
      <main className="grid w-full max-w-[1120px] overflow-hidden rounded-3xl md:min-h-[556px] md:grid-cols-[minmax(0,0.95fr)_minmax(0,1.05fr)] md:overflow-visible md:rounded-none">
        <BrandPanel />

        <section className="border-border bg-card px-8 py-10 sm:px-12 md:rounded-r-[28px] md:border md:border-l-0 md:px-[70px] md:py-[72px]">
          <p className="text-[15px] font-semibold text-primary">
            <span className="mr-2">01</span>Login and authentication
          </p>
          <h1 className="mt-6 text-4xl font-bold tracking-tight text-brand-navy">Welcome back</h1>
          <div className="max-w-[412px]">
            <LoginForm />
          </div>
        </section>
      </main>

      <p className="mt-6 w-full max-w-[1120px] px-2 text-xs text-muted-foreground">
        Demo environment: SSO with Microsoft Entra ID requires enterprise configuration.
      </p>
    </div>
  )
}
