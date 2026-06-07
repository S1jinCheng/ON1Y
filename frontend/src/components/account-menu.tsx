"use client";

import { ChevronDown, LogOut, Settings } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import { SettingsCenter } from "@/components/settings-center";
import { fetchAuthStatus, fetchCurrentUser, logout, type AuthUser } from "@/lib/api";
import type { Locale } from "@/lib/i18n";
import { OPEN_SETTINGS_EVENT, SETTINGS_CLOSED_EVENT } from "@/lib/open-settings";

export function AccountMenu(props: {
  locale: Locale;
  onLocaleChange?: (locale: Locale) => void;
  onMessage?: (message: string) => void;
}): JSX.Element {
  const router = useRouter();
  const [user, setUser] = useState<AuthUser | null>(null);
  const [authRequired, setAuthRequired] = useState(true);
  const [open, setOpen] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const ref = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    let cancelled = false;
    void fetchAuthStatus()
      .then((status) => {
        if (!cancelled) {
          setAuthRequired(status.auth_required);
        }
      })
      .catch(() => {
        /* ignore */
      });
    return () => {
      cancelled = true;
    };
  }, []);

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

  useEffect(() => {
    const openHandler = (): void => {
      setOpen(false);
      setSettingsOpen(true);
    };
    window.addEventListener(OPEN_SETTINGS_EVENT, openHandler);
    return () => window.removeEventListener(OPEN_SETTINGS_EVENT, openHandler);
  }, []);

  const name = user?.display_name || user?.username || "";
  const initial = name ? name.charAt(0).toUpperCase() : "?";

  return (
    <>
      <div className="relative" ref={ref}>
        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          className="inline-flex items-center gap-1.5 rounded-md border border-border bg-surface px-2 py-1.5 text-sm hover:bg-soft"
        >
          <span className="flex h-5 w-5 items-center justify-center rounded-full bg-inverse text-[11px] font-semibold text-inverse-foreground">
            {initial}
          </span>
          <span className="max-w-[7rem] truncate text-foreground">{name}</span>
          <ChevronDown className="h-3.5 w-3.5 text-muted" />
        </button>

        {open ? (
          <div className="absolute right-0 z-50 mt-1.5 w-44 overflow-hidden rounded-lg border border-border bg-surface py-1 shadow-lg">
            <button
              type="button"
              className="flex w-full items-center gap-2.5 px-3 py-2 text-left text-sm text-foreground hover:bg-soft"
              onClick={() => {
                setOpen(false);
                setSettingsOpen(true);
              }}
            >
              <Settings className="h-4 w-4 text-muted" />
              {props.locale === "zh" ? "设置" : "Settings"}
            </button>
            {authRequired ? (
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
            ) : null}
          </div>
        ) : null}
      </div>

      <SettingsCenter
        open={settingsOpen}
        onClose={() => {
          setSettingsOpen(false);
          window.dispatchEvent(new Event(SETTINGS_CLOSED_EVENT));
        }}
        locale={props.locale}
        user={user}
        onUserUpdated={setUser}
        onLocaleChange={props.onLocaleChange}
        onMessage={props.onMessage}
      />
    </>
  );
}
