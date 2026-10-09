import { ApiError } from "../../api/client";

export function signInErrorMessage(error: unknown): { tone: "error" | "warn"; text: string } {
  if (error instanceof ApiError) {
    switch (error.code) {
      case "account_locked":
        return { tone: "warn", text: error.message };
      case "rate_limited":
        return { tone: "warn", text: "Too many attempts from this device. Wait a minute, then try again." };
      case "invalid_credentials":
        return { tone: "error", text: "Email or password is incorrect." };
      case "network_error":
      case "timeout":
        return { tone: "error", text: "SiteSense can't be reached. Check your connection and try again." };
    }
  }
  return { tone: "error", text: "Sign-in failed. Please try again." };
}
