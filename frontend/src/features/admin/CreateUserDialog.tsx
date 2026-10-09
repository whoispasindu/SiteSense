import { useState, type SubmitEvent } from "react";
import { z } from "zod";

import { useCreateUser, useSites } from "../../api/admin";
import { ROLE_LABELS, ROLES, roleSchema, type Role } from "../../api/auth";
import { Alert } from "../../components/ui/Alert";
import { Button } from "../../components/ui/Button";
import { Dialog } from "../../components/ui/Dialog";
import { SelectField, TextField } from "../../components/ui/Field";
import { SiteCheckboxes, TemporaryPassword } from "./shared";
import { errorText, isSiteScoped } from "./adminUtils";

const newUserSchema = z.object({
  email: z.email("Enter a valid email address."),
  full_name: z.string().trim().min(2, "Enter the person's full name.").max(120),
  role: roleSchema,
});

type Errors = Partial<Record<"email" | "full_name", string>>;

export function CreateUserDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const createUser = useCreateUser();
  const sites = useSites();
  const [role, setRole] = useState<Role>("site_engineer");
  const [siteIds, setSiteIds] = useState<string[]>([]);
  const [errors, setErrors] = useState<Errors>({});
  const [created, setCreated] = useState<{ name: string; password: string } | null>(null);

  function close() {
    setCreated(null);
    setErrors({});
    setSiteIds([]);
    createUser.reset();
    onClose();
  }

  function onSubmit(event: SubmitEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const parsed = newUserSchema.safeParse({ email: form.get("email"), full_name: form.get("full_name"), role });
    if (!parsed.success) {
      const next: Errors = {};
      for (const issue of parsed.error.issues) {
        const field = issue.path[0];
        if (field === "email" || field === "full_name") next[field] ??= issue.message;
      }
      setErrors(next);
      return;
    }
    setErrors({});
    createUser.mutate(
      { ...parsed.data, site_ids: isSiteScoped(role) ? siteIds : [] },
      {
        onSuccess: (result) => {
          setCreated({ name: result.user.full_name, password: result.temporary_password });
        },
      },
    );
  }

  return (
    <Dialog open={open} onClose={close} title={created ? "Account created" : "Add a user"}>
      {created ? (
        <TemporaryPassword password={created.password} name={created.name} onDone={close} />
      ) : (
        <form noValidate onSubmit={onSubmit} className="space-y-5">
          {createUser.isError ? <Alert tone="error">{errorText(createUser.error)}</Alert> : null}
          <TextField label="Full name" name="full_name" autoComplete="off" error={errors.full_name} />
          <TextField label="Email" name="email" type="email" autoComplete="off" spellCheck={false} error={errors.email} />
          <SelectField
            label="Role"
            value={role}
            onChange={(e) => {
              setRole(roleSchema.parse(e.target.value));
            }}
            hint={isSiteScoped(role) ? "Works only on the sites you assign." : "Works across all sites."}
          >
            {ROLES.map((r) => (
              <option key={r} value={r}>
                {ROLE_LABELS[r]}
              </option>
            ))}
          </SelectField>
          {isSiteScoped(role) ? (
            <SiteCheckboxes sites={sites.data ?? []} selected={siteIds} onChange={setSiteIds} />
          ) : null}
          <div className="flex justify-end gap-3 border-t border-rule pt-4">
            <Button onClick={close}>Cancel</Button>
            <Button type="submit" variant="primary" disabled={createUser.isPending}>
              {createUser.isPending ? "Creating…" : "Create account"}
            </Button>
          </div>
        </form>
      )}
    </Dialog>
  );
}
