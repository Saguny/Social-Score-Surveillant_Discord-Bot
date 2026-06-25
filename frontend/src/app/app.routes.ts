import { Routes } from '@angular/router';

import { HomePage } from './home-page/home-page';
import { PrivacyPage } from './privacy-page/privacy-page';
import { TosPage } from './tos-page/tos-page';
import { LeaderboardPage } from './leaderboard-page/leaderboard-page';
import { DashboardPage } from './dashboard-page/dashboard-page';
import { AboutPage } from './about-page/about-page';

export const routes: Routes = [
    {
    path: "",
    redirectTo: "",
    pathMatch: "full"
    },
    {
    path: "",
    title: "Home ★ SCS",
    component: HomePage
    },
    {
        path: "privacy",
        title: "Privacy Policy ★ SCS",
        component: PrivacyPage
    },
    {
        path: "tos",
        title: "Terms of Service ★ SCS",
        component: TosPage
    },
    {
        path: "leaderboard",
        title: "Leaderboard ★ SCS",
        component: LeaderboardPage
    },
    {
        path: "dashboard",
        title: "Dashboard ★ SCS",
        component: DashboardPage
    },
    {
        path: "about",
        title: "About ★ SCS",
        component: AboutPage
    }
];