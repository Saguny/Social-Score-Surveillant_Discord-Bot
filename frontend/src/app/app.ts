import { Component } from '@angular/core';
import { RouterOutlet, RouterLink } from '@angular/router';
import { Overlay } from './overlay/overlay';
import { OverlayService } from './app-services/overlay-service';

@Component({
  selector: 'app-root',
  imports: [RouterOutlet, RouterLink, Overlay],
  templateUrl: './app.html',
  styleUrl: './app.css'
})
export class App {
  constructor(
    public overlay: OverlayService
  ) {}

  leaderboardMenu = "Leaderboard";
  dashboardMenu = "Dashboard";

  selectMenu(menu?: String) {
    if (menu === undefined) {
      this.dashboardMenu = "Dashboard";
      this.leaderboardMenu = "Leaderboard";
    }
    if (menu === 'dashboard') {
      this.dashboardMenu = "★ Dashboard";
      this.leaderboardMenu = "Leaderboard";
    } else if (menu === 'leaderboard') {
      this.leaderboardMenu = "★ Leaderboard";
      this.dashboardMenu = "Dashboard";
    } else {
      this.dashboardMenu = "Dashboard";
      this.leaderboardMenu = "Leaderboard";
    }
  }
}
