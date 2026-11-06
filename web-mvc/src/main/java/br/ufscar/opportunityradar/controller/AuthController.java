package br.ufscar.opportunityradar.controller;

import br.ufscar.opportunityradar.service.AccountService;
import java.security.Principal;
import java.nio.file.Path;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Controller;
import org.springframework.ui.Model;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.servlet.mvc.support.RedirectAttributes;

@Controller
public class AuthController {
    private final AccountService accounts;
    private final boolean temporaryCatalogDatabase;
    public AuthController(AccountService accounts,
                          @Value("${radar.db.path}") String configuredDb) {
        this.accounts = accounts;
        this.temporaryCatalogDatabase = "classroom_latest.db".equalsIgnoreCase(
            Path.of(configuredDb).getFileName().toString());
    }

    @GetMapping("/login")
    public String login(Principal principal, Model model) {
        model.addAttribute("temporaryCatalogDatabase", temporaryCatalogDatabase);
        return principal == null ? "auth/login" : "redirect:/favorites";
    }

    @GetMapping("/register")
    public String register(Principal principal, Model model) {
        model.addAttribute("temporaryCatalogDatabase", temporaryCatalogDatabase);
        return principal == null ? "auth/register" : "redirect:/favorites";
    }

    @PostMapping("/register")
    public String createAccount(@RequestParam(defaultValue = "") String username,
                                @RequestParam(defaultValue = "") String password,
                                @RequestParam(defaultValue = "") String confirmPassword,
                                Model model, RedirectAttributes redirect) {
        try {
            accounts.register(username, password, confirmPassword);
            redirect.addFlashAttribute("message", "Conta criada! Entre com seu usuário e senha.");
            return "redirect:/login";
        } catch (IllegalArgumentException problem) {
            model.addAttribute("error", problem.getMessage());
            model.addAttribute("username", username);
            return "auth/register";
        }
    }

    @GetMapping("/profile")
    public String profile(Principal principal, jakarta.servlet.http.HttpSession session, Model model) {
        model.addAttribute("username", principal.getName());
        if (Boolean.TRUE.equals(session.getAttribute("radarMigrationWarning"))) {
            model.addAttribute("migrationWarning", true);
            session.removeAttribute("radarMigrationWarning");
        }
        return "profile";
    }
}
