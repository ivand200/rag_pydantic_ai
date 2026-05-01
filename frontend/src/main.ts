import { clerkPlugin } from "@clerk/vue";
import { createApp } from "vue";

import App from "./App.vue";
import "./styles.css";

const clerkPublishableKey = import.meta.env.VITE_CLERK_PUBLISHABLE_KEY;

const app = createApp(App);

if (clerkPublishableKey) {
  app.use(clerkPlugin, {
    publishableKey: clerkPublishableKey
  });
}

app.mount("#app");
