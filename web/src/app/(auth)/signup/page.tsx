"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { CircleAlertIcon, Loader2Icon } from "lucide-react";
import Link from "next/link";
import { useForm } from "react-hook-form";
import type { z } from "zod";

import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import {
  Form,
  FormControl,
  FormDescription,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from "@/components/ui/form";
import { Input } from "@/components/ui/input";
import { ApiError, errorMessage } from "@/lib/api/errors";
import { signupSchema } from "@/lib/auth/form-schemas";
import { useAuth } from "@/lib/auth/use-session";

// The backend answers a duplicate email with 422 (FastCRUD's DuplicateValueException), not 409.
const DUPLICATE_EMAIL_DETAIL = "Email is already registered";

export default function SignupPage() {
  const { signup } = useAuth();
  const form = useForm<z.input<typeof signupSchema>, unknown, z.output<typeof signupSchema>>({
    resolver: zodResolver(signupSchema),
    defaultValues: { firstName: "", lastName: "", email: "", password: "" },
  });

  const onSubmit = form.handleSubmit(async (values) => {
    try {
      await signup(values);
    } catch (error) {
      if (error instanceof ApiError && error.detail === DUPLICATE_EMAIL_DETAIL) {
        form.setError("email", { message: "An account with this email already exists." }, { shouldFocus: true });
      } else {
        form.setError("root", { message: errorMessage(error) });
      }
    }
  });

  const rootError = form.formState.errors.root?.message;

  return (
    <Card className="gap-5 px-6">
      <h1 className="font-serif text-title font-medium">Create your account</h1>
      <CardContent className="flex flex-col gap-5 px-0">
        <Form {...form}>
          <form onSubmit={onSubmit} noValidate className="flex flex-col gap-4">
            <div className="grid grid-cols-2 gap-3">
              <FormField
                control={form.control}
                name="firstName"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>First name</FormLabel>
                    <FormControl>
                      <Input autoComplete="given-name" {...field} />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />
              <FormField
                control={form.control}
                name="lastName"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>
                      Last name <span className="font-normal text-ink-3">(optional)</span>
                    </FormLabel>
                    <FormControl>
                      <Input autoComplete="family-name" {...field} />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />
            </div>
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
                    <Input type="password" autoComplete="new-password" {...field} />
                  </FormControl>
                  <FormDescription>At least 8 characters.</FormDescription>
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
              Create account
            </Button>
          </form>
        </Form>
        <p className="text-center text-sm text-ink-2">
          Already have an account?{" "}
          <Link href="/login" className="font-medium text-accent underline">
            Sign in
          </Link>
        </p>
      </CardContent>
    </Card>
  );
}
