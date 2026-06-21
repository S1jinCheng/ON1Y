import type { BookAcquireCandidate } from "@/lib/book-types";

const PUNCT_RE = /[/／,，、;；|]+/;
const PUBLISHER_RE = /出版社|出版集团|出版公司|书局|书社|Press|Publishing/i;

function looksLikePublisher(text: string | null | undefined): boolean {
  const t = text?.trim();
  if (!t) return false;
  return PUBLISHER_RE.test(t) || /^\d{4}([-/年]\d{1,2})?$/.test(t);
}

function norm(text: string): string {
  return text.replace(/\s+/g, "").toLowerCase();
}

function cleanToken(text: string): string {
  return text
    .trim()
    .replace(/\s*译\s*$/, "")
    .replace(/等\s*$/, "")
    .trim();
}

function extractTranslatorTokens(translator: string | null | undefined): string[] {
  const raw = translator?.trim();
  if (!raw) return [];
  const parts = raw.split(PUNCT_RE).map((p) => p.trim()).filter(Boolean);
  const chunks = parts.length > 0 ? parts : [raw];
  return chunks.map(cleanToken).filter((t) => t.length >= 2);
}

function parseTranslatorFromCandidate(candidate: BookAcquireCandidate): string | null {
  const blob = [candidate.title, candidate.author, candidate.publisher].filter(Boolean).join(" ");
  const semi = blob.match(/著\s*;\s*([^;，,]+?)\s*译/);
  if (semi?.[1]) {
    const name = semi[1].trim();
    if (name.length >= 2 && name.length <= 30) return name;
  }
  const plain = blob.match(/([\u4e00-\u9fff·A-Za-z]{2,30})\s*译/g);
  if (!plain) return null;
  for (const match of plain) {
    const m = match.match(/([\u4e00-\u9fff·A-Za-z]{2,30})\s*译/);
    const name = m?.[1]?.trim();
    if (name && name !== "翻" && name !== "编") return name;
  }
  return null;
}

function tokensOverlap(left: string, right: string): boolean {
  const a = norm(left);
  const b = norm(right);
  if (!a || !b) return false;
  return a.includes(b) || b.includes(a);
}

export function translatorMatchesHint(
  hint: string | null | undefined,
  candidate: BookAcquireCandidate
): boolean {
  const raw = hint?.trim();
  if (!raw) return true;
  if (looksLikePublisher(raw)) return true;

  const blob = [candidate.title, candidate.author, candidate.publisher].filter(Boolean).join(" ");
  const blobNorm = norm(blob);
  const hintNorm = norm(raw);

  if (hintNorm && blobNorm.includes(hintNorm)) return true;

  for (const token of extractTranslatorTokens(raw)) {
    if (blobNorm.includes(norm(token))) return true;
  }

  const parsed = parseTranslatorFromCandidate(candidate);
  if (parsed) {
    if (tokensOverlap(raw, parsed)) return true;
    for (const token of extractTranslatorTokens(raw)) {
      if (tokensOverlap(token, parsed)) return true;
    }
  }

  return false;
}

export function candidateDoubanMismatch(
  doubanTranslator: string | null | undefined,
  candidate: BookAcquireCandidate
): boolean {
  const tr = doubanTranslator?.trim();
  if (!tr) return false;
  return !translatorMatchesHint(tr, candidate);
}
