import { useEffect, useId, useLayoutEffect, useRef, useState, type ComponentPropsWithoutRef, type ReactNode } from 'react';
import { Eye, EyeOff } from 'lucide-react';

type PasswordInputProps = Omit<ComponentPropsWithoutRef<'input'>, 'type' | 'children'> & {
  label: ReactNode;
  hint?: ReactNode;
};

export function PasswordInput({ id, label, hint, 'aria-describedby': describedBy, ...props }: PasswordInputProps) {
  const generatedId = useId();
  const inputId = id ?? generatedId;
  const hintId = `${inputId}-hint`;
  const inputRef = useRef<HTMLInputElement>(null);
  const selection = useRef<{ start: number; end: number; direction: 'forward' | 'backward' | 'none' } | null>(null);
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    const form = inputRef.current?.form;
    const hide = () => setVisible(false);
    form?.addEventListener('submit', hide, true);
    return () => form?.removeEventListener('submit', hide, true);
  }, [props.form]);

  useLayoutEffect(() => {
    const saved = selection.current;
    if (saved) inputRef.current?.setSelectionRange(saved.start, saved.end, saved.direction);
    selection.current = null;
  }, [visible]);

  function toggleVisibility() {
    const input = inputRef.current;
    if (input && input.selectionStart !== null && input.selectionEnd !== null) {
      selection.current = { start: input.selectionStart, end: input.selectionEnd, direction: input.selectionDirection ?? 'none' };
    }
    setVisible(value => !value);
  }

  return <span className="password-field">
    <label htmlFor={inputId}>{label}</label>
    <span className="password-input">
      <input autoCapitalize="none" spellCheck={false} {...props} ref={inputRef} id={inputId} type={visible ? 'text' : 'password'} aria-describedby={hint ? [describedBy, hintId].filter(Boolean).join(' ') : describedBy} />
      <button type="button" className="password-toggle" disabled={props.disabled} aria-label={visible ? 'Ocultar contraseña' : 'Mostrar contraseña'} aria-pressed={visible} aria-controls={inputId}
        onPointerDown={event => { if (event.button === 0 && document.activeElement === inputRef.current) event.preventDefault(); }} onClick={toggleVisibility}>
        {visible ? <EyeOff size={18} aria-hidden="true" /> : <Eye size={18} aria-hidden="true" />}
      </button>
    </span>
    {hint && <small id={hintId}>{hint}</small>}
  </span>;
}
