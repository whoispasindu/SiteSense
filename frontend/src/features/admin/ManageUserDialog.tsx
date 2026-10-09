import { useState } from "react";

import { useAssignSites, useResetPassword, useSites, useUpdateUser, type AdminUser } from "../../api/admin";
import { ROLE_LABELS, ROLES, roleSchema, type Role } from "../../api/auth";
import { useAuth } from "../../auth/context";
import { Alert } from "../../components/ui/Alert";
import { Button } from "../../components/ui/Button";
import { Dialog } from "../../components/ui/Dialog";
import { SelectField } from "../../components/ui/Field";
import { SiteCheckboxes, TemporaryPassword, UserStatus } from "./shared";
import { errorText, isSiteScoped } from "./adminUtils";

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="space-y-3 border-t border-dashed border-rule pt-5 first:border-t-0 first:pt-0">
      <h3 className="font-wide text-[0.7rem] font-extrabold tracking-[0.16em] text-ink-soft uppercase">{title}</h3>
      {children}
    </section>
  );
}

export function ManageUserDialog({ user, onClose }: { user: AdminUser | null; onClose: () => void }) {
  const { user: me } = useAuth();
  const sites = useSites();
  const updateUser = useUpdateUser();
  const assignSites = useAssignSites();
  const resetPassword = useResetPassword();
  const [role, setRole] = useState<Role | null>(null);
  const [siteIds, setSiteIds] = useState<string[] | null>(null);
  const [confirming, setConfirming] = useState<"deactivate" | "reset" | null>(null);
  const [temporary, setTemporary] = useState<string | null>(null);

  if (!user) return null;

  const isSelf = me?.id === user.id;
  const chosenRole = role ?? user.role;
  const chosenSites = siteIds ?? user.sites.map((s) => s.id);
  const error = updateUser.error ?? assignSites.error ?? resetPassword.error;

  function close() {
    setRole(null);
    setSiteIds(null);
    setConfirming(null);
    setTemporary(null);
    updateUser.reset();
    assignSites.reset();
    resetPassword.reset();
    onClose();
  }

  if (temporary) {
    return (
      <Dialog open onClose={close} title="Password reset" code="U-RST">
        <TemporaryPassword password={temporary} name={user.full_name} onDone={close} />
      </Dialog>
    );
  }

  return (
    <Dialog open onClose={close} title={user.full_name} code={`U-${user.id.slice(0, 4).toUpperCase()}`}>
      <div className="space-y-5">
        <div className="flex flex-wrap items-center gap-3 text-sm">
          <span className="text-ink-soft">{user.email}</span>
          <UserStatus user={user} />
        </div>
        {error ? <Alert tone="error">{errorText(error)}</Alert> : null}

        <Section title="Role">
          <div className="flex flex-wrap items-end gap-3">
            <div className="min-w-56 flex-1">
              <SelectField
                label="Role"
                value={chosenRole}
                disabled={isSelf}
                hint={isSelf ? "You cannot change your own role." : undefined}
                onChange={(e) => {
                  setRole(roleSchema.parse(e.target.value));
                }}
              >
                {ROLES.map((r) => (
                  <option key={r} value={r}>
                    {ROLE_LABELS[r]}
                  </option>
                ))}
              </SelectField>
            </div>
            <Button
              disabled={isSelf || chosenRole === user.role || updateUser.isPending}
              onClick={() => {
                updateUser.mutate({ id: user.id, role: chosenRole }, { onSuccess: close });
              }}
            >
              Save role
            </Button>
          </div>
        </Section>

        {isSiteScoped(user.role) ? (
          <Section title="Site access">
            <SiteCheckboxes sites={sites.data ?? []} selected={chosenSites} onChange={setSiteIds} />
            <Button
              disabled={siteIds === null || assignSites.isPending}
              onClick={() => {
                assignSites.mutate({ id: user.id, siteIds: chosenSites }, { onSuccess: close });
              }}
            >
              Save sites
            </Button>
          </Section>
        ) : null}

        {!isSelf ? (
          <Section title="Account">
            {confirming ? (
              <Alert tone="warn" title={confirming === "reset" ? "Reset this password?" : "Deactivate this account?"}>
                {confirming === "reset"
                  ? "Their current password stops working and every device is signed out."
                  : "They are signed out everywhere immediately and cannot sign in until reactivated."}
                <div className="mt-3 flex gap-3">
                  <Button
                    onClick={() => {
                      setConfirming(null);
                    }}
                  >
                    Keep
                  </Button>
                  <Button
                    variant="primary"
                    onClick={() => {
                      if (confirming === "reset") {
                        resetPassword.mutate(user.id, {
                          onSuccess: (r) => {
                            setTemporary(r.temporary_password);
                          },
                        });
                      } else {
                        updateUser.mutate({ id: user.id, is_active: false }, { onSuccess: close });
                      }
                    }}
                  >
                    {confirming === "reset" ? "Reset password" : "Deactivate"}
                  </Button>
                </div>
              </Alert>
            ) : (
              <div className="flex flex-wrap gap-3">
                <Button
                  disabled={!user.is_active}
                  onClick={() => {
                    setConfirming("reset");
                  }}
                >
                  Reset password
                </Button>
                {user.is_active ? (
                  <Button
                    variant="ghost"
                    className="text-signal-high"
                    onClick={() => {
                      setConfirming("deactivate");
                    }}
                  >
                    Deactivate
                  </Button>
                ) : (
                  <Button
                    onClick={() => {
                      updateUser.mutate({ id: user.id, is_active: true }, { onSuccess: close });
                    }}
                  >
                    Reactivate
                  </Button>
                )}
              </div>
            )}
          </Section>
        ) : null}
      </div>
    </Dialog>
  );
}
