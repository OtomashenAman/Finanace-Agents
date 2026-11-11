import type { ReactNode } from "react"
import { Link } from "react-router"

/** Who publishes these terms: fill in before going live (shown as "to be added" when empty).
 *  Draft wording for the company's legal review; it describes what the app actually does. */
const LEGAL = {
  company: "e-Solutions Inc.",
  product: "Finance AI",
  contactEmail: "", // e.g. the privacy or support mailbox
  address: "", // the company's registered postal address
  governingLaw: "", // e.g. "the State of New Jersey, United States"
  effective: "November 11, 2026",
}

function Pending({ value, what }: { value: string; what: string }) {
  return value ? <>{value}</> : <span className="rounded bg-amber-100 px-1 text-amber-900">[{what}: to be added]</span>
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="space-y-2">
      <h2 className="text-lg font-semibold text-brand-navy">{title}</h2>
      <div className="space-y-2 text-sm leading-6 text-foreground/90">{children}</div>
    </section>
  )
}

function LegalFrame({ title, other, children }: { title: string; other: { to: string; label: string }; children: ReactNode }) {
  return (
    <div className="min-h-svh bg-brand-page px-4 py-10">
      <article className="mx-auto max-w-3xl space-y-6 rounded-2xl border border-border bg-card p-6 shadow-sm sm:p-10">
        <header className="space-y-1 border-b border-border pb-4">
          <p className="text-sm font-medium text-primary">
            {LEGAL.company} · {LEGAL.product}
          </p>
          <h1 className="text-3xl font-bold tracking-tight text-brand-navy">{title}</h1>
          <p className="text-xs text-muted-foreground">Effective {LEGAL.effective}</p>
        </header>
        {children}
        <footer className="flex flex-wrap gap-4 border-t border-border pt-4 text-sm">
          <Link to={other.to} className="text-primary hover:underline">
            {other.label}
          </Link>
          <Link to="/login" className="text-primary hover:underline">
            Sign in
          </Link>
        </footer>
      </article>
    </div>
  )
}

const Contact = () => (
  <>
    Contact us at <Pending value={LEGAL.contactEmail} what="contact email" />, or write to {LEGAL.company},{" "}
    <Pending value={LEGAL.address} what="postal address" />.
  </>
)

export function PrivacyPage() {
  return (
    <LegalFrame title="Privacy policy" other={{ to: "/legal/terms", label: "Terms of use (end-user license agreement)" }}>
      <p className="text-sm leading-6">
        This policy explains what information {LEGAL.product} ("the app"), provided by {LEGAL.company} ("we", "us"), collects,
        how we use it, and the choices you have. The app is a finance operations tool used by businesses and their authorised
        staff; it is not intended for consumers or for children.
      </p>

      <Section title="Information we collect">
        <p>
          <strong>Account information:</strong> the name, work email address and role of each person given access by their
          organisation, and a securely hashed password.
        </p>
        <p>
          <strong>Accounting data from QuickBooks Online</strong>, when your organisation connects a company: vendors, purchase
          orders, bills, the chart of accounts, customers, invoices, payments and purchases, and reports such as the profit and
          loss. We request only the QuickBooks "accounting" permission.
        </p>
        <p>
          <strong>Information you provide in the app:</strong> purchase requests, invoices and other documents you upload,
          vendor and client details submitted through the app's secure forms (including bank details), messages, approvals and
          notes.
        </p>
        <p>
          <strong>Usage and security records:</strong> an audit trail of actions taken in the app (who did what, and when) and
          technical logs such as IP address and browser, used to keep the service secure.
        </p>
      </Section>

      <Section title="How we use it">
        <p>
          To provide the service your organisation uses: preparing and checking finance work (such as matching invoices, payment
          runs, reconciliations and billing), showing it to the people who review and approve it, and keeping a record of
          decisions.
        </p>
        <p>
          <strong>Writing to QuickBooks:</strong> the app changes your QuickBooks data only after an authorised person approves
          the change in the app, for example recording an approval on a bill or creating an approved bill. Otherwise it only
          reads.
        </p>
        <p>We do not sell personal information, use it for advertising, or use your data to train AI models.</p>
      </Section>

      <Section title="AI processing">
        <p>
          Some features use AI to read documents and draft content, through Microsoft Azure OpenAI Service under our agreement
          with Microsoft. Under that agreement, the content we send is not used to train Microsoft's or OpenAI's models. AI
          output is checked against the source data where possible, and decisions remain with the people using the app.
        </p>
      </Section>

      <Section title="Sharing">
        <p>We share information only with:</p>
        <ul className="list-disc space-y-1 pl-5">
          <li>the people your organisation authorises in the app;</li>
          <li>
            service providers that run the service for us (cloud hosting and database, email delivery, and Microsoft Azure
            OpenAI), bound by confidentiality and data-protection terms;
          </li>
          <li>Intuit, when the app reads from or, after approval, writes to your QuickBooks company;</li>
          <li>authorities, where the law requires it.</li>
        </ul>
      </Section>

      <Section title="Security">
        <p>
          Data is encrypted in transit (HTTPS). QuickBooks connection tokens and app credentials are stored encrypted, and bank
          account numbers are encrypted at rest and shown only masked. Access requires an individual account, and every action
          is recorded in a tamper-evident audit trail.
        </p>
      </Section>

      <Section title="Retention">
        <p>
          We keep data for as long as your organisation uses the service. The audit trail is kept for seven years for financial
          record-keeping. Your organisation can disconnect QuickBooks at any time, which revokes the app's access, and can ask
          us to delete its data, subject to legal retention requirements.
        </p>
      </Section>

      <Section title="Your choices and rights">
        <p>
          Your organisation controls who has access and which companies are connected. You may ask to access, correct or delete
          your personal information; we will respond as required by applicable law, usually through your organisation's
          administrator.
        </p>
      </Section>

      <Section title="Changes and contact">
        <p>
          We may update this policy; the effective date above shows the latest version. <Contact />
        </p>
      </Section>
    </LegalFrame>
  )
}

export function TermsPage() {
  return (
    <LegalFrame title="Terms of use (end-user license agreement)" other={{ to: "/legal/privacy", label: "Privacy policy" }}>
      <p className="text-sm leading-6">
        These terms govern your use of {LEGAL.product} ("the app"), provided by {LEGAL.company} ("we", "us"). By signing in or
        using the app you agree to them on behalf of yourself and the organisation that gave you access.
      </p>

      <Section title="License">
        <p>
          We grant your organisation a limited, non-exclusive, non-transferable right for its authorised users to use the app
          for its internal finance operations while its subscription or agreement with us is in force. You may not copy,
          resell, reverse engineer or misuse the app, or try to access data you are not authorised to see.
        </p>
      </Section>

      <Section title="Accounts">
        <p>
          Access is by individual account. Keep your credentials confidential and tell your administrator promptly about any
          unauthorised use. Your organisation decides who has access and in what role.
        </p>
      </Section>

      <Section title="QuickBooks and other connected services">
        <p>
          When your organisation connects QuickBooks Online, you authorise the app to read the data described in our privacy
          policy and, after an authorised person approves in the app, to record changes such as approved bills. Your use of
          QuickBooks remains subject to Intuit's own terms. You can disconnect at any time from the app or from QuickBooks.
        </p>
      </Section>

      <Section title="Your data">
        <p>
          Your organisation keeps all rights to its data. You give us permission to process it only to provide and support the
          service, as described in the privacy policy. You are responsible for the accuracy of the data you provide and for
          having the right to provide it.
        </p>
      </Section>

      <Section title="AI-assisted work and your decisions">
        <p>
          The app's agents prepare, check and draft finance work, and AI output may contain errors. Approvals, payments,
          postings and other decisions are made by your authorised users, who remain responsible for reviewing them. The app is
          a tool and does not provide accounting, tax or legal advice.
        </p>
      </Section>

      <Section title="Availability and changes">
        <p>
          We aim to keep the app available and secure but do not guarantee uninterrupted service. We may improve or change
          features; where a change materially reduces what the app does, we will tell your organisation in advance.
        </p>
      </Section>

      <Section title="Disclaimer and limitation of liability">
        <p>
          To the extent the law allows, the app is provided "as is", without warranties of any kind, and neither we nor our
          suppliers are liable for indirect, incidental or consequential losses, or for losses arising from decisions made
          using the app. Our total liability is limited to the amounts your organisation paid us for the app in the twelve
          months before the claim. Your organisation's written agreement with us, if any, prevails over these terms.
        </p>
      </Section>

      <Section title="Ending use">
        <p>
          Your organisation may stop using the app at any time. We may suspend access that breaks these terms or puts the
          service or others at risk. On ending, the app's access to QuickBooks is revoked, and data is handled as the privacy
          policy describes.
        </p>
      </Section>

      <Section title="Governing law and contact">
        <p>
          These terms are governed by the laws of <Pending value={LEGAL.governingLaw} what="governing law" />. <Contact />
        </p>
      </Section>
    </LegalFrame>
  )
}
