"use client";

import { Loader2, QrCode, Smartphone, X } from "lucide-react";
import QRCode from "qrcode";
import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";

import {
  cancelTelegramQrLogin,
  completeTelegramQrPassword,
  pollTelegramQrLogin,
  sendTelegramAuthCode,
  signInTelegramAuth,
  startTelegramQrLogin,
  type TelegramQrLoginView
} from "@/lib/api";
import type { Locale } from "@/lib/i18n";

function L(locale: Locale, zh: string, en: string): string {
  return locale === "zh" ? zh : en;
}

type LoginMethod = "qr" | "phone";

type Props = {
  locale: Locale;
  open: boolean;
  method: LoginMethod;
  forceRelogin?: boolean;
  onClose: () => void;
  onSuccess: () => void;
  onMessage?: (message: string) => void;
};

const inputClass =
  "w-full rounded-lg border border-border bg-surface px-3 py-2 text-sm text-foreground outline-none focus:border-accent";
const ghostBtn =
  "rounded-lg border border-border bg-surface px-3 py-2 text-sm text-foreground hover:bg-soft disabled:opacity-50";
const primaryBtn =
  "rounded-lg border border-foreground bg-inverse px-3 py-2 text-sm text-inverse-foreground hover:opacity-90 disabled:opacity-50";

export function TelegramLoginDialog(props: Props): JSX.Element | null {
  const { locale, open, method, onClose, onSuccess, onMessage } = props;
  const [mounted, setMounted] = useState(false);
  const [activeMethod, setActiveMethod] = useState<LoginMethod>(method);
  const [session, setSession] = useState<TelegramQrLoginView | null>(null);
  const [qrDataUrl, setQrDataUrl] = useState<string | null>(null);
  const [qrGenerating, setQrGenerating] = useState(false);
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [password, setPassword] = useState("");
  const [submittingPassword, setSubmittingPassword] = useState(false);
  const [phone, setPhone] = useState("");
  const [code, setCode] = useState("");
  const [phonePassword, setPhonePassword] = useState("");
  const [authBusy, setAuthBusy] = useState(false);
  const sessionIdRef = useRef<string | null>(null);
  const callbacksRef = useRef({ onClose, onSuccess, onMessage });
  callbacksRef.current = { onClose, onSuccess, onMessage };

  useEffect(() => {
    setMounted(true);
  }, []);

  useEffect(() => {
    setActiveMethod(method);
  }, [method, open]);

  useEffect(() => {
    if (!open || activeMethod !== "qr") {
      const sid = sessionIdRef.current;
      sessionIdRef.current = null;
      if (sid) {
        void cancelTelegramQrLogin(sid);
      }
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

    void startTelegramQrLogin(props.forceRelogin ?? false)
      .then((view) => {
        if (cancelled) {
          return;
        }
        if (view.status === "authorized") {
          callbacksRef.current.onMessage?.(
            L(locale, "Telegram 已登录", "Signed in to Telegram")
          );
          callbacksRef.current.onSuccess();
          callbacksRef.current.onClose();
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
        void cancelTelegramQrLogin(sid);
      }
    };
  }, [open, activeMethod, locale, props.forceRelogin]);

  useEffect(() => {
    if (!session?.url) {
      setQrDataUrl(null);
      setQrGenerating(false);
      return;
    }
    let cancelled = false;
    setQrDataUrl(null);
    setQrGenerating(true);
    void QRCode.toDataURL(session.url, { width: 220, margin: 1, errorCorrectionLevel: "M" })
      .then((url) => {
        if (!cancelled) {
          setQrDataUrl(url);
          // #region agent log
          fetch("http://127.0.0.1:7651/ingest/9914abac-1aa5-422c-92cf-5c3feb176a32", {
            method: "POST",
            headers: { "Content-Type": "application/json", "X-Debug-Session-Id": "3ec0ad" },
            body: JSON.stringify({
              sessionId: "3ec0ad",
              hypothesisId: "F",
              location: "telegram-login-dialog:qrRender",
              message: "qr rendered",
              data: {
                urlPrefix: session.url.slice(0, 32),
                urlLen: session.url.length
              },
              timestamp: Date.now()
            })
          }).catch(() => {});
          // #endregion
        }
      })
      .catch((err) => {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : String(err));
        }
      })
      .finally(() => {
        if (!cancelled) {
          setQrGenerating(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [session?.url]);

  useEffect(() => {
    if (!open || activeMethod !== "qr" || !session?.session_id) {
      return;
    }
    if (
      session.status === "authorized" ||
      session.status === "error" ||
      session.status === "cancelled" ||
      session.status === "needs_password"
    ) {
      return;
    }

    const sessionId = session.session_id;
    const pollMs = session.url ? 1500 : 400;
    const timer = window.setInterval(() => {
      void pollTelegramQrLogin(sessionId)
        .then((view) => {
          setSession((prev) => {
            if (
              prev?.status === view.status &&
              prev?.url === view.url &&
              prev?.message === view.message
            ) {
              return prev;
            }
            return view;
          });
          if (view.status === "authorized") {
            window.clearInterval(timer);
            sessionIdRef.current = null;
            callbacksRef.current.onMessage?.(
              L(locale, "Telegram 已登录", "Signed in to Telegram")
            );
            callbacksRef.current.onSuccess();
            callbacksRef.current.onClose();
          } else if (view.status === "error") {
            window.clearInterval(timer);
            sessionIdRef.current = null;
            const message = view.message ?? L(locale, "登录失败", "Sign-in failed");
            setError(message);
            callbacksRef.current.onMessage?.(message);
          }
        })
        .catch((err) => {
          // #region agent log
          fetch("http://127.0.0.1:7651/ingest/9914abac-1aa5-422c-92cf-5c3feb176a32", {
            method: "POST",
            headers: { "Content-Type": "application/json", "X-Debug-Session-Id": "3ec0ad" },
            body: JSON.stringify({
              sessionId: "3ec0ad",
              hypothesisId: "D",
              location: "telegram-login-dialog:poll",
              message: "poll failed",
              data: { error: err instanceof Error ? err.message : String(err) },
              timestamp: Date.now()
            })
          }).catch(() => {});
          // #endregion
        });
    }, pollMs);

    return () => window.clearInterval(timer);
  }, [open, activeMethod, session?.session_id, session?.status, session?.url, locale]);

  function handleClose(): void {
    const sid = sessionIdRef.current;
    sessionIdRef.current = null;
    if (sid) {
      void cancelTelegramQrLogin(sid);
    }
    setPhone("");
    setCode("");
    setPhonePassword("");
    setPassword("");
    setError(null);
    callbacksRef.current.onClose();
  }

  async function submitQrPassword(): Promise<void> {
    const sid = session?.session_id ?? sessionIdRef.current;
    if (!sid) {
      return;
    }
    setSubmittingPassword(true);
    try {
      await completeTelegramQrPassword(sid, password.trim());
      sessionIdRef.current = null;
      callbacksRef.current.onMessage?.(L(locale, "Telegram 已登录", "Signed in to Telegram"));
      callbacksRef.current.onSuccess();
      handleClose();
    } catch (err) {
      callbacksRef.current.onMessage?.(err instanceof Error ? err.message : String(err));
    } finally {
      setSubmittingPassword(false);
    }
  }

  async function sendCode(): Promise<void> {
    setAuthBusy(true);
    try {
      await sendTelegramAuthCode(phone.trim());
      callbacksRef.current.onMessage?.(L(locale, "验证码已发送", "Verification code sent"));
    } catch (err) {
      callbacksRef.current.onMessage?.(err instanceof Error ? err.message : String(err));
    } finally {
      setAuthBusy(false);
    }
  }

  async function confirmSignIn(): Promise<void> {
    setAuthBusy(true);
    try {
      const result = await signInTelegramAuth({
        phone: phone.trim(),
        code: code.trim(),
        password: phonePassword.trim() || undefined
      });
      if (result.ok) {
        callbacksRef.current.onMessage?.(L(locale, "Telegram 已登录", "Signed in to Telegram"));
        callbacksRef.current.onSuccess();
        handleClose();
      }
    } catch (err) {
      callbacksRef.current.onMessage?.(err instanceof Error ? err.message : String(err));
    } finally {
      setAuthBusy(false);
    }
  }

  if (!open || !mounted) {
    return null;
  }

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
              {L(locale, "登录 Telegram", "Sign in to Telegram")}
            </h3>
            <p className="mt-1 text-[11px] leading-relaxed text-muted">
              {L(
                locale,
                "扫码或手机号登录你的 Telegram 账号",
                "Sign in with QR code or phone number"
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

        <div className="mb-4 inline-flex overflow-hidden rounded-lg border border-border text-sm">
          <button
            type="button"
            onClick={() => setActiveMethod("qr")}
            className={`inline-flex items-center gap-1.5 px-3 py-2 transition ${
              activeMethod === "qr"
                ? "bg-inverse text-inverse-foreground"
                : "bg-surface text-muted hover:bg-soft"
            }`}
          >
            <QrCode className="h-3.5 w-3.5" />
            {L(locale, "扫码", "QR")}
          </button>
          <button
            type="button"
            onClick={() => setActiveMethod("phone")}
            className={`inline-flex items-center gap-1.5 px-3 py-2 transition ${
              activeMethod === "phone"
                ? "bg-inverse text-inverse-foreground"
                : "bg-surface text-muted hover:bg-soft"
            }`}
          >
            <Smartphone className="h-3.5 w-3.5" />
            {L(locale, "手机号", "Phone")}
          </button>
        </div>

        {activeMethod === "qr" ? (
          session?.status === "needs_password" ? (
            <div className="space-y-2">
              <input
                type="password"
                className={inputClass}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder={L(locale, "两步验证密码", "2FA password")}
              />
              <button
                type="button"
                className={`w-full ${primaryBtn}`}
                disabled={submittingPassword || !password.trim()}
                onClick={() => void submitQrPassword()}
              >
                {submittingPassword ? L(locale, "验证中…", "Verifying…") : L(locale, "确认", "Confirm")}
              </button>
            </div>
          ) : (
            <div className="flex flex-col items-center gap-3 py-2">
              {starting || qrGenerating || (session?.session_id && !qrDataUrl) ? (
                <Loader2 className="h-8 w-8 animate-spin text-muted" />
              ) : error ? (
                <div className="flex h-[220px] w-[220px] items-center justify-center rounded-lg border border-dashed border-red-500/30 bg-red-500/5 px-4 text-center text-xs text-red-600">
                  {error}
                </div>
              ) : qrDataUrl ? (
                // eslint-disable-next-line @next/next/no-img-element
                <img
                  key={session?.url ?? "qr"}
                  src={qrDataUrl}
                  alt="Telegram QR"
                  className="h-[220px] w-[220px] rounded-lg border border-border bg-white p-2"
                />
              ) : (
                <Loader2 className="h-8 w-8 animate-spin text-muted" />
              )}
              <p className="text-center text-xs leading-relaxed text-muted">
                {L(
                  locale,
                  "必须用 Telegram 内置扫码：手机 Telegram → 设置 → 设备 → 扫码登录（不可用微信/相机扫码）",
                  "Use Telegram's built-in scanner: Telegram app → Settings → Devices → Link Desktop Device (not WeChat/camera)"
                )}
              </p>
              <p className="text-center text-[11px] leading-relaxed text-muted/80">
                {L(
                  locale,
                  "扫码后请在手机上点「确认」；二维码约 30 秒刷新一次",
                  "Tap Confirm on your phone after scanning; the QR code refreshes about every 30 seconds"
                )}
              </p>
            </div>
          )
        ) : (
          <div className="space-y-2">
            <input
              className={inputClass}
              value={phone}
              onChange={(e) => setPhone(e.target.value)}
              placeholder="+86..."
            />
            <div className="flex flex-wrap gap-2">
              <button type="button" className={ghostBtn} disabled={authBusy} onClick={() => void sendCode()}>
                {L(locale, "发送验证码", "Send code")}
              </button>
              <input
                className={`${inputClass} max-w-[120px]`}
                value={code}
                onChange={(e) => setCode(e.target.value)}
                placeholder={L(locale, "验证码", "Code")}
              />
            </div>
            <input
              className={inputClass}
              type="password"
              value={phonePassword}
              onChange={(e) => setPhonePassword(e.target.value)}
              placeholder={L(locale, "两步验证（如有）", "2FA password")}
            />
            <button
              type="button"
              className={`w-full ${primaryBtn}`}
              disabled={authBusy}
              onClick={() => void confirmSignIn()}
            >
              {L(locale, "确认登录", "Sign in")}
            </button>
          </div>
        )}
      </div>
    </div>
  );

  return createPortal(dialog, document.body);
}
