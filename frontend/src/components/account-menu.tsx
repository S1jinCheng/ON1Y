"use client";

import { ChevronDown, LogOut, Settings } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import { SettingsCenter } from "@/components/settings-center";
import { fetchCurrentUser, logout, type AuthUser } from "@/lib/api";
import type { Locale } from "@/lib/i18n";

export function AccountMenu(props: { locale: Locale; onMessage?: (message: string) => void }): JSX.Element {
  const router = useRouter();
  const [user, setUser] = useState<AuthUser | null>(null);
  const [open, setOpen] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const ref = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    let cancelled = false;
    void fetchCurrentUser()
      .then((payload) => {
        if (!cancelled) {
          setUser(payload.user);
        }
      })
      .catch(() => {
        /* AuthGate handles redirect */
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    function onClick(event: MouseEvent): void {
      if (ref.current && !ref.current.contains(event.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", onClick);
    return () => document.removeEventListener("mousedown", onClick);
  }, []);

  const name = user?.display_name || user?.username || "";
  const initial = name ? name.charAt(0).toUpperCase() : "?";

  return (
    <>
      <div className="relative" ref={ref}>
        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          className="inline-flex items-center gap-1.5 rounded-md border border-border bg-white px-2 py-1.5 text-sm hover:bg-soft"
        >
          <span className="flex h-5 w-5 items-center justify-center rounded-full bg-black text-[11px] font-semibold text-white">
            {initial}
          </span>
          <span className="max-w-[7rem] truncate text-neutral-700">{name}</span>
          <ChevronDown className="h-3.5 w-3.5 text-neutral-400" />
        </button>

        {open ? (
          <div className="absolute right-0 z-50 mt-1.5 w-44 overflow-hidden rounded-lg border border-neutral-200 bg-white py-1 shadow-lg">
            <button
              type="button"
              className="flex w-full items-center gap-2.5 px-3 py-2 text-left text-sm text-neutral-700 hover:bg-neutral-50"
              onClick={() => {
                setOpen(false);
                setSettingsOpen(true);
              }}
            >
              <Settings className="h-4 w-4 text-neutral-400" />
              {props.locale === "zh" ? "设置" : "Settings"}
            </button>
            <button
              type="button"
              className="flex w-full items-center gap-2.5 px-3 py-2 text-left text-sm text-red-600 hover:bg-red-50"
              onClick={() => {
                logout();
                router.replace("/login");
              }}
            >
              <LogOut className="h-4 w-4" />
              {props.locale === "zh" ? "退出登录" : "Log out"}
            </button>
          </div>
        ) : null}
      </div>

      <SettingsCenter
        open={settingsOpen}
        onClose={() => setSettingsOpen(false)}
        locale={props.locale}
        user={user}
        onUserUpdated={setUser}
        onMessage={props.onMessage}
      />
    </>
  );
}
