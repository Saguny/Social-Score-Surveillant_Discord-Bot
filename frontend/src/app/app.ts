import { Component, signal } from '@angular/core';
import { RouterOutlet, RouterLink } from '@angular/router';

@Component({
  selector: 'app-root',
  imports: [RouterOutlet, RouterLink],
  templateUrl: './app.html',
  styleUrl: './app.css'
})
export class App {
  leaderboardMenu = "Leaderboard";
  dashboardMenu = "Dashboard";
  login(){
  }

  theme(){
  }

  selectMenu(menu?: String) {
    if(menu === undefined){
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
