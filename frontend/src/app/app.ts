import { Component } from '@angular/core';
import { RouterOutlet, RouterLink } from '@angular/router';
import { OverlayService } from './app-services/overlay-service';
import { Overlay } from './overlay/overlay';

@Component({
  selector: 'app-root',
  imports: [RouterOutlet, RouterLink, Overlay],
  templateUrl: './app.html',
  styleUrl: './app.css'
})
export class App {
  constructor(
    private overlay: OverlayService
  ) { }

  leaderboardMenu = "Leaderboard";
  dashboardMenu = "Dashboard";
  login() {
    this.overlay.showOverlay("info", "Test", "Test123");
  }

  theme() {
  }

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
