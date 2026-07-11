import React from "react";
import ExpandMoreIcon from "@mui/icons-material/ExpandMore";
import { Accordion, AccordionDetails, AccordionSummary, Box, Chip, Typography } from "@mui/material";

export default function LTXSection({ title, description, badge, defaultExpanded = false, children }) {
  return (
    <Accordion defaultExpanded={defaultExpanded} disableGutters sx={{ mb: 1.5, borderRadius: 2, overflow: "hidden" }}>
      <AccordionSummary expandIcon={<ExpandMoreIcon />}>
        <Box sx={{ display: "flex", alignItems: "center", gap: 1, minWidth: 0 }}>
          <Box sx={{ minWidth: 0 }}>
            <Typography variant="subtitle1" fontWeight={700}>{title}</Typography>
            {description ? <Typography variant="caption" color="text.secondary">{description}</Typography> : null}
          </Box>
          {badge ? <Chip label={badge} size="small" variant="outlined" /> : null}
        </Box>
      </AccordionSummary>
      <AccordionDetails>{children}</AccordionDetails>
    </Accordion>
  );
}
