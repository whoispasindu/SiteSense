import { useMemo, useState } from "react";

import { useUsers, type AdminUser } from "../../api/admin";
import { ROLE_LABELS, ROLES, type Role } from "../../api/auth";
import { Alert } from "../../components/ui/Alert";
import { Button } from "../../components/ui/Button";
import { PageHeader } from "../../components/ui/PageHeader";
import { Sheet } from "../../components/ui/Sheet";
import { CreateUserDialog } from "../../features/admin/CreateUserDialog";
import { ManageUserDialog } from "../../features/admin/ManageUserDialog";
import { UserStatus } from "../../features/admin/shared";
import { errorText, formatDateTime, isSiteScoped } from "../../features/admin/adminUtils";

export function UsersPage() {
  const users = useUsers();
  const [creating, setCreating] = useState(false);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [roleFilter, setRoleFilter] = useState<Role | "all">("all");

  const visible = useMemo(() => {
    const q = query.trim().toLowerCase();
    return (users.data?.items ?? []).filter(
      (u) =>
        (roleFilter === "all" || u.role === roleFilter) &&
        (!q || u.full_name.toLowerCase().includes(q) || u.email.includes(q)),
    );
  }, [users.data, query, roleFilter]);

  const selected: AdminUser | null = users.data?.items.find((u) => u.id === selectedId) ?? null;

  return (
    <div className="mx-auto max-w-6xl space-y-8">
      <PageHeader
        sheet="A-01"
        title="Users"
        description="Create accounts, set roles and decide which sites each person works on. Every change is written to the audit log."
        action={
          <Button
            variant="primary"
            onClick={() => {
              setCreating(true);
            }}
          >
            Add user
          </Button>
        }
      />

      <div className="flex flex-wrap items-center gap-3">
        <label className="min-w-0 flex-1 sm:max-w-xs">
          <span className="sr-only">Search users</span>
          <input
            type="search"
            placeholder="Search name or email"
            value={query}
            onChange={(e) => {
              setQuery(e.target.value);
            }}
            className="min-h-11 w-full rounded-[var(--radius-sheet)] border-2 border-rule-strong bg-paper-raised px-3 focus:border-ink focus:outline-none"
          />
        </label>
        <div role="group" aria-label="Filter by role" className="flex flex-wrap gap-1.5">
          {(["all", ...ROLES] as const).map((r) => (
            <button
              key={r}
              type="button"
              aria-pressed={roleFilter === r}
              onClick={() => {
                setRoleFilter(r);
              }}
              className={`min-h-9 rounded-full border px-3 text-xs font-semibold ${
                roleFilter === r ? "border-ink bg-ink text-paper" : "border-rule-strong text-ink-soft hover:border-ink"
              }`}
            >
              {r === "all" ? "All" : ROLE_LABELS[r]}
            </button>
          ))}
        </div>
      </div>

      {users.isError ? <Alert tone="error">{errorText(users.error)}</Alert> : null}

      <Sheet sheetCode={`${String(visible.length)} / ${String(users.data?.total ?? 0)}`} className="overflow-hidden">
        <table className="w-full text-left text-sm">
          <caption className="sr-only">Company users</caption>
          <thead className="border-b border-rule-strong bg-paper-sunk">
            <tr className="font-mono text-[0.65rem] tracking-[0.14em] text-ink-soft uppercase">
              <th scope="col" className="px-4 py-2.5 font-normal">
                Person
              </th>
              <th scope="col" className="hidden px-4 py-2.5 font-normal sm:table-cell">
                Role
              </th>
              <th scope="col" className="hidden px-4 py-2.5 font-normal lg:table-cell">
                Sites
              </th>
              <th scope="col" className="px-4 py-2.5 font-normal">
                Status
              </th>
              <th scope="col" className="hidden px-4 py-2.5 font-normal md:table-cell">
                Last sign-in
              </th>
              <th scope="col" className="px-4 py-2.5 font-normal">
                <span className="sr-only">Actions</span>
              </th>
            </tr>
          </thead>
          <tbody className="divide-y divide-rule">
            {users.isPending ? (
              <tr>
                <td colSpan={6} className="px-4 py-10 text-center text-ink-faint">
                  Loading users…
                </td>
              </tr>
            ) : visible.length === 0 ? (
              <tr>
                <td colSpan={6} className="px-4 py-10 text-center text-ink-faint">
                  No users match.
                </td>
              </tr>
            ) : (
              visible.map((user) => (
                <tr key={user.id} className={user.is_active ? "" : "text-ink-faint"}>
                  <td className="px-4 py-3">
                    <p className="font-semibold">{user.full_name}</p>
                    <p className="text-xs text-ink-faint">{user.email}</p>
                    <p className="mt-1 text-xs text-ink-soft sm:hidden">{user.role_label}</p>
                  </td>
                  <td className="hidden px-4 py-3 sm:table-cell">{user.role_label}</td>
                  <td className="hidden px-4 py-3 lg:table-cell">
                    {isSiteScoped(user.role) ? (
                      user.sites.length ? (
                        <span className="flex flex-wrap gap-1">
                          {user.sites.map((s) => (
                            <span key={s.id} className="rounded-[2px] bg-paper-sunk px-1.5 py-0.5 font-mono text-[0.68rem]">
                              {s.code}
                            </span>
                          ))}
                        </span>
                      ) : (
                        <span className="text-xs text-signal-medium">None assigned</span>
                      )
                    ) : (
                      <span className="text-xs text-ink-faint">All sites</span>
                    )}
                  </td>
                  <td className="px-4 py-3">
                    <UserStatus user={user} />
                  </td>
                  <td className="tabular hidden px-4 py-3 font-mono text-xs md:table-cell">
                    {formatDateTime(user.last_login_at)}
                  </td>
                  <td className="px-4 py-3 text-right">
                    <Button
                      variant="ghost"
                      aria-label={`Manage ${user.full_name}`}
                      onClick={() => {
                        setSelectedId(user.id);
                      }}
                    >
                      Manage
                    </Button>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </Sheet>

      <CreateUserDialog
        open={creating}
        onClose={() => {
          setCreating(false);
        }}
      />
      <ManageUserDialog
        key={selectedId ?? "none"}
        user={selected}
        onClose={() => {
          setSelectedId(null);
        }}
      />
    </div>
  );
}
