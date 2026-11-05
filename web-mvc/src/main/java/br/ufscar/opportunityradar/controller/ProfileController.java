package br.ufscar.opportunityradar.controller;

import br.ufscar.opportunityradar.config.VisitorIdentityFilter;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import java.security.SecureRandom;
import java.time.Duration;
import java.util.HexFormat;
import org.springframework.http.HttpHeaders;
import org.springframework.http.ResponseCookie;
import org.springframework.stereotype.Controller;
import org.springframework.ui.Model;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestAttribute;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.servlet.mvc.support.RedirectAttributes;

@Controller
public class ProfileController {
    private static final SecureRandom RANDOM = new SecureRandom();

    @GetMapping("/profile")
    public String profile(@RequestAttribute(VisitorIdentityFilter.ATTRIBUTE) String visitor, Model model) {
        model.addAttribute("recoveryCode", visitor);
        return "profile";
    }

    @PostMapping("/profile/restore")
    public String restore(@RequestParam String recoveryCode, HttpServletRequest request,
                          HttpServletResponse response, RedirectAttributes flash) {
        String code = recoveryCode == null ? "" : recoveryCode.strip().toLowerCase();
        if (!code.matches("[a-f0-9]{64}")) {
            flash.addFlashAttribute("error", "Código inválido. Confira os 64 caracteres.");
            return "redirect:/profile";
        }
        issueCookie(response, request, code);
        flash.addFlashAttribute("message", "Perfil restaurado neste navegador.");
        return "redirect:/favorites";
    }

    @PostMapping("/profile/new")
    public String newProfile(HttpServletRequest request, HttpServletResponse response,
                             RedirectAttributes flash) {
        byte[] token = new byte[32];
        RANDOM.nextBytes(token);
        issueCookie(response, request, HexFormat.of().formatHex(token));
        flash.addFlashAttribute("message", "Novo perfil criado. O anterior permanece salvo.");
        return "redirect:/profile";
    }

    private static void issueCookie(HttpServletResponse response, HttpServletRequest request, String value) {
        response.addHeader(HttpHeaders.SET_COOKIE, ResponseCookie.from(VisitorIdentityFilter.COOKIE, value)
            .httpOnly(true).secure(request.isSecure()).sameSite("Lax")
            .path("/").maxAge(Duration.ofDays(365)).build().toString());
    }
}
