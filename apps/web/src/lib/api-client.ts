import axios, { type AxiosInstance } from "axios";

const baseURL = import.meta.env["VITE_API_URL"] ?? "http://localhost:4000";

export const apiClient: AxiosInstance = axios.create({
  baseURL,
  withCredentials: true,
  timeout: 10_000,
  headers: { "Content-Type": "application/json" },
});
