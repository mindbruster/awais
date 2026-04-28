import {
  ChangeEvent,
  InputHTMLAttributes,
  ReactNode,
  SelectHTMLAttributes,
  TextareaHTMLAttributes,
} from "react";

interface BaseProps {
  label: string;
  required?: boolean;
  error?: string | null;
  hint?: string;
}

export function Field({
  label,
  required,
  error,
  hint,
  children,
}: BaseProps & { children: ReactNode }) {
  return (
    <label className="block">
      <span className="mb-1 block text-sm font-medium text-slate-700">
        {label}
        {required && <span className="ml-0.5 text-red-500">*</span>}
      </span>
      {children}
      {error ? (
        <span className="mt-1 block text-xs text-red-600">{error}</span>
      ) : hint ? (
        <span className="mt-1 block text-xs text-slate-500">{hint}</span>
      ) : null}
    </label>
  );
}

type TextProps = BaseProps & InputHTMLAttributes<HTMLInputElement>;

export function TextField({ label, required, error, hint, ...rest }: TextProps) {
  return (
    <Field label={label} required={required} error={error} hint={hint}>
      <input className="input" required={required} {...rest} />
    </Field>
  );
}

type SelectProps = BaseProps & SelectHTMLAttributes<HTMLSelectElement> & {
  options: { value: string | number; label: string }[];
};

export function SelectField({ label, required, error, hint, options, ...rest }: SelectProps) {
  return (
    <Field label={label} required={required} error={error} hint={hint}>
      <select className="input" required={required} {...rest}>
        {options.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>
    </Field>
  );
}

type TextareaProps = BaseProps & TextareaHTMLAttributes<HTMLTextAreaElement>;

export function TextArea({ label, required, error, hint, ...rest }: TextareaProps) {
  return (
    <Field label={label} required={required} error={error} hint={hint}>
      <textarea className="input min-h-[80px]" required={required} {...rest} />
    </Field>
  );
}

export function controlled<T extends string | number>(
  value: T,
  setValue: (v: T) => void,
): { value: T; onChange: (e: ChangeEvent<HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement>) => void } {
  return {
    value,
    onChange: (e) => {
      const v = e.target.value;
      setValue((typeof value === "number" ? Number(v) : v) as T);
    },
  };
}
