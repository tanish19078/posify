import { ArrowRight, Search } from "lucide-react";
import { useState, type FormEvent, type ReactNode } from "react";
import { Button, ErrorPanel, Field } from "./ui";
export function Filter({
  value,
  change,
  placeholder,
}: {
  value: string;
  change: (value: string) => void;
  placeholder: string;
}) {
  return (
    <div className="search-field">
      <Search size={17} />
      <input
        aria-label={placeholder}
        placeholder={placeholder}
        value={value}
        onChange={(e) => change(e.target.value)}
      />
    </div>
  );
}
export function MutationForm({
  children,
  submit,
  label = "Save record",
}: {
  children: ReactNode;
  submit: (data: FormData) => Promise<void>;
  label?: string;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function save(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setBusy(true);
    setError("");
    const data = new FormData(e.currentTarget);
    try {
      await submit(data);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <form onSubmit={save}>
      {children}
      {error && <ErrorPanel message={error} />}
      <div className="form-actions">
        <Button busy={busy}>
          {label}
          <ArrowRight size={16} />
        </Button>
      </div>
    </form>
  );
}
export const text = (d: FormData, k: string) => String(d.get(k) || "").trim();
export function Input({
  label,
  name,
  required = true,
  value,
  type = "text",
}: {
  label: string;
  name: string;
  required?: boolean;
  value?: string;
  type?: string;
}) {
  return (
    <Field label={label}>
      <input
        name={name}
        required={required}
        defaultValue={value}
        type={type}
        min={type === "number" ? 1 : undefined}
        maxLength={200}
      />
    </Field>
  );
}
