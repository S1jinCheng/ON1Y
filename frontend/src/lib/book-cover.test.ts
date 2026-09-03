import { describe, expect, it } from "vitest";

import { bookCoverSrc } from "@/lib/book-cover";

describe("bookCoverSrc", () => {
  it("uses the backend route without a trailing slash", () => {
    expect(bookCoverSrc("https://img1.doubanio.com/view/subject/m/public/s1.jpg")).toBe(
      "/api/books/cover?url=https%3A%2F%2Fimg1.doubanio.com%2Fview%2Fsubject%2Fm%2Fpublic%2Fs1.jpg"
    );
  });

  it("normalizes previously generated proxy URLs", () => {
    expect(bookCoverSrc("/api/books/cover/?url=https%3A%2F%2Fexample.com%2Fcover.jpg")).toBe(
      "/api/books/cover?url=https%3A%2F%2Fexample.com%2Fcover.jpg"
    );
  });
});
