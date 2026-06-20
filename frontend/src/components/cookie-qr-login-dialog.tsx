"use client";

import { Loader2, QrCode, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import QRCode from "qrcode";

import {
  cancelCookieQrLogin,
  pollCookieQrLogin,
  startCookieQrLogin,
  type CookiePlatform,
  type CookieQrLoginView
} from "@/lib/api";
import type { Locale } from "@/lib/i18n";

function L(locale: Locale, zh: string, en: string): string {
  return locale === "zh" ? zh : en;
}

type Props = {
  locale: Locale;
  platform: CookiePlatform;
  platformLabel: string;
  open: boolean;
  onClose: () => void;
  onSuccess: () => void;
  onMessage?: (message: string) => void;
};

export function CookieQrLoginDialog(props: Props): JSX.Element | null {
  const { locale, platform, platformLabel, open, onClose, onSuccess, onMessage } = props;
  const [mounted, setMounted] = useState(false);
  const [session, setSession] = useState<CookieQrLoginView | null>(null);
  const [qrDataUrl, setQrDataUrl] = useState<string | null>(null);
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const sessionIdRef = useRef<string | null>(null);
  const callbacksRef = useRef({ onClose, onSuccess, onMessage });
  callbacksRef.current = { onClose, onSuccess, onMessage };

  useEffect(() => {
    setMounted(true);
  }, []);

  useEffect(() => {
    if (!open) {
      setSession(null);
      setQrDataUrl(null);
      setError(null);
      setStarting(false);
      return;
    }

    let cancelled = false;
    setStarting(true);
    setError(null);
    setSession(null);
    setQrDataUrl(null);
    sessionIdRef.current = null;

    void startCookieQrLogin(platform)
      .then((view) => {
        if (cancelled) {
          return;
        }
        sessionIdRef.current = view.session_id;
        setSession(view);
      })
      .catch((err) => {
        if (cancelled) {
          return;
        }
        const message = err instanceof Error ? err.message : String(err);
        setError(message);
        callbacksRef.current.onMessage?.(message);
      })
      .finally(() => {
        if (!cancelled) {
          setStarting(false);
        }
      });

    return () => {
      cancelled = true;
      const sid = sessionIdRef.current;
      sessionIdRef.current = null;
      if (sid) {
        void cancelCookieQrLogin(platform, sid);
      }
    };
  }, [open, platform]);

  useEffect(() => {
    if (!session?.qr_content) {
      setQrDataUrl(null);
      return;
    }
    let cancelled = false;
    void QRCode.toDataURL(session.qr_content, { width: 220, margin: 1 }).then((url) => {
      if (!cancelled) {
        setQrDataUrl(url);
      }
    });
    return () => {
      cancelled = true;
    };
  }, [session?.qr_content]);

  useEffect(() => {
    if (!open || !session?.session_id) {
      return;
    }
    if (session.status === "success" || session.status === "error" || session.status === "expired") {
      return;
    }

    const sessionId = session.session_id;
    const timer = window.setInterval(() => {
      void pollCookieQrLogin(platform, sessionId).then((view) => {
        setSession(view);
        if (view.status === "success") {
          window.clearInterval(timer);
          sessionIdRef.current = null;
          callbacksRef.current.onMessage?.(
            L(locale, `${platformLabel} 登录成功`, `${platformLabel} sign-in succeeded`)
          );
          callbacksRef.current.onSuccess();
          callbacksRef.current.onClose();
        } else if (view.status === "error" || view.status === "expired") {
          window.clearInterval(timer);
          sessionIdRef.current = null;
          const message = view.message ?? L(locale, "登录失败", "Sign-in failed");
          setError(message);
          callbacksRef.current.onMessage?.(message);
        }
      });
    }, 1500);

    return () => window.clearInterval(timer);
  }, [open, session?.session_id, session?.status, platform, platformLabel, locale]);

  function handleClose(): void {
    const sid = sessionIdRef.current;
    sessionIdRef.current = null;
    if (sid) {
      void cancelCookieQrLogin(platform, sid);
    }
    callbacksRef.current.onClose();
  }

  if (!open || !mounted) {
    return null;
  }

  const statusLabel = (() => {
    if (error) {
      return error;
    }
    if (starting || !session) {
      return L(locale, "正在准备…", "Preparing…");
    }
    if (session.method === "browser") {
      return L(
        locale,
        "请在弹出的浏览器窗口中完成登录",
        "Complete sign-in in the browser window"
      );
    }
    if (session.status === "scanned") {
      return L(locale, "已扫码，请在手机上确认登录", "Scanned — confirm on your phone");
    }
    if (session.status === "pending" && !session.qr_content) {
      return L(locale, "正在加载二维码…", "Loading QR code…");
    }
    if (session.status === "pending") {
      return L(locale, "等待扫码…", "Waiting for scan…");
    }
    return session.message ?? session.status;
  })();

  const dialog = (
    <div
      className="fixed inset-0 z-[200] flex items-center justify-center bg-black/50 p-4"
      onClick={(e) => {
        if (e.target === e.currentTarget) {
          handleClose();
        }
      }}
    >
      <div
        role="dialog"
        aria-modal="true"
        className="w-full max-w-sm rounded-xl border border-border bg-surface p-5 shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-3 flex items-start justify-between gap-3">
          <div>
            <h3 className="text-sm font-semibold text-foreground">
              {L(locale, `${platformLabel} 登录`, `Sign in to ${platformLabel}`)}
            </h3>
            <p className="mt-1 text-[11px] leading-relaxed text-muted">
              {session?.hint ??
                L(
                  locale,
                  "使用官方 App 扫码或浏览器登录",
                  "Use the official app to scan or sign in via browser"
                )}
            </p>
          </div>
          <button
            type="button"
            className="rounded-lg p-1 text-muted hover:bg-soft hover:text-foreground"
            onClick={handleClose}
            aria-label={L(locale, "关闭", "Close")}
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="flex flex-col items-center gap-3 py-2">
          {starting ? (
            <Loader2 className="h-8 w-8 animate-spin text-muted" />
          ) : session?.method === "app_scan" && qrDataUrl ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img
              src={qrDataUrl}
              alt="QR"
              className="h-[220px] w-[220px] rounded-lg border border-border bg-white p-2"
            />
          ) : session?.method === "app_scan" && !qrDataUrl && !error ? (
            <Loader2 className="h-8 w-8 animate-spin text-muted" />
          ) : session?.method === "browser" ? (
            <div className="flex h-[220px] w-[220px] items-center justify-center rounded-lg border border-dashed border-border bg-soft">
              <QrCode className="h-12 w-12 text-muted" />
            </div>
          ) : error ? (
            <div className="flex h-[220px] w-[220px] items-center justify-center rounded-lg border border-dashed border-red-500/30 bg-red-500/5 px-4 text-center text-xs text-red-600 dark:text-red-400">
              {error}
            </div>
          ) : null}
          <p className="text-center text-xs text-muted">{statusLabel}</p>
          {error ? (
            <button
              type="button"
              className="rounded-lg border border-border px-3 py-1.5 text-xs text-foreground hover:bg-soft"
              onClick={() => {
                setError(null);
                setStarting(true);
                void startCookieQrLogin(platform)
                  .then((view) => {
                    sessionIdRef.current = view.session_id;
                    setSession(view);
                  })
                  .catch((err) => {
                    const message = err instanceof Error ? err.message : String(err);
                    setError(message);
                  })
                  .finally(() => setStarting(false));
              }}
            >
              {L(locale, "重试", "Retry")}
            </button>
          ) : null}
        </div>
      </div>
    </div>
  );

  return createPortal(dialog, document.body);
}
