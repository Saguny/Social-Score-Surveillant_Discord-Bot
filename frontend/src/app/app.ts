import { Component } from '@angular/core';
import { RouterOutlet } from '@angular/router';
import { Overlay } from './overlay/overlay';
import { Footer } from './footer/footer';
import { Header } from './header/header';

@Component({
  selector: 'app-root',
  imports: [RouterOutlet, Overlay, Footer, Header],
  templateUrl: './app.html',
  styleUrl: './app.css'
})
export class App {
}
