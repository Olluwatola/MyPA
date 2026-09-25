"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { CircleAlertIcon, Loader2Icon } from "lucide-react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useForm } from "react-hook-form";
import type { z } from "zod";

import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Form, FormControl, FormField, FormItem, FormLabel, FormMessage } from "@/components/ui/form";
import { Input } from "@/components/ui/input";
import { Separator } from "@/components/ui/separator";
import { errorMessage } from "@/lib/api/errors";
import { loginSchema } from "@/lib/auth/form-schemas";
import { useAuth } from "@/lib/auth/use-session";

export default function LoginPage() {
  const { login } = useAuth();
  const searchParams = useSearchParams();
  const form = useForm<z.input<typeof loginSchema>, unknown, z.output<typeof loginSchema>>({
    resolver: zodResolver(loginSchema),
    defaultValues: { email: "", password: "" },
  });

  const onSubmit = form.handleSubmit(async ({ email, password }) => {
    try {
      await login(email, password);
    } catch (error) {
      // About this form, so inline rather than a toast. A 401's detail is "Wrong email or password."
      form.setError("root", { message: errorMessage(error) });
    }
  });

  const rootError =
    form.formState.errors.root?.message ??
    (searchParams.get("error") === "google" ? "Google sign-in didn't work. Try again, or use your email." : null);

  return (
    <Card className="gap-5 px-6">
      <h1 className="font-serif text-title font-medium">Sign in</h1>
      <CardContent className="flex flex-col gap-5 px-0">
        <Form {...form}>
          <form onSubmit={onSubmit} noValidate className="flex flex-col gap-4">
            <FormField
              control={form.control}
              name="email"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Email</FormLabel>
                  <FormControl>
                    <Input type="email" autoComplete="email" {...field} />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />
            <FormField
              control={form.control}
              name="password"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Password</FormLabel>
                  <FormControl>
                    <Input type="password" autoComplete="current-password" {...field} />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />
            {rootError && (
              <p role="alert" className="flex items-center gap-1.5 text-sm text-danger">
                <CircleAlertIcon aria-hidden className="size-4 shrink-0" />
                {rootError}
              </p>
            )}
            <Button type="submit" disabled={form.formState.isSubmitting}>
              {form.formState.isSubmitting && <Loader2Icon aria-hidden className="animate-spin" />}
              Sign in
            </Button>
          </form>
        </Form>
        <div className="flex items-center gap-3 text-xs text-ink-3">
          <Separator className="flex-1" />
          or
          <Separator className="flex-1" />
        </div>
        {/* A plain navigation: the backend runs the whole Google redirect flow. */}
        <Button asChild variant="outline">
          <a href="/api/v1/auth/google/login">Continue with Google</a>
        </Button>
        <p className="text-center text-sm text-ink-2">
          New here?{" "}
          <Link href="/signup" className="font-medium text-accent underline">
            Create an account
          </Link>
        </p>
      </CardContent>
    </Card>
  );
}
