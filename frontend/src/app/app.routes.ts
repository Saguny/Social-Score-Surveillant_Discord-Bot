import { Routes } from '@angular/router';

import { HomePage } from './home-page/home-page';

export const routes: Routes = [
    {
    path: "",
    redirectTo: "home",
    pathMatch: "full"
    },
    {
    path: "",
    component: HomePage,
    title: "Home - SCS"
    }
];
